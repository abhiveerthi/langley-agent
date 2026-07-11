"""
B-Roll Producer — writes original AI b-roll scripts and (when configured)
renders them into short clips via Higgsfield, then files them in the creator's
Dropbox organized by date & topic.

Three intents:

  draft_broll    — WRITE b-roll prompts/scripts from Braden's topics + the
                   weekly direction. Pure LLM, structured output — works fully
                   with NO Higgsfield key. The plan (a BRollPlan of clips, each
                   with prompt + aspect_ratio + duration) is surfaced as a
                   structured frontend card and best-effort exported to Storage
                   as kind="script".
  generate_broll — actually submit the drafted prompts to Higgsfield, await the
                   ~5–10s interrupt-style clips (16:9 landscape primary, 9:16
                   for Shorts), and deposit them into Dropbox under
                   /B-Roll/<date>/<topic>/. Degrades gracefully when no
                   HIGGSFIELD_API_KEY is set — reports "not configured" instead
                   of failing. Re-running a bad clip is just regenerating it.
  general        — anything text-only (questions about a prior plan, "what can
                   you make", etc.).

Graph shape (mirrors the other agents so the orchestrator drives it the same):

  START → load_profile → load_peer_context → classify_intent
                                                  ↓
              ┌───────────────────────────────────┼──────────────────┐
          draft_broll                         generate_broll        general
              ↓                                     ↓                  ↓
          draft_scripts                        generate_clips          │
              ↓                                     ↓                  │
          persist_script                       organize_dropbox        │
              ↓                                     ↓                  ↓
              └────────────────────────► respond ◄──────────── general_answer

No write tools fire automatically and there's no HITL gate — drafting is
read-only, and generation/Dropbox deposit are creator-initiated.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, END, START
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.peer_context import _is_real_uuid
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.agents.broll.tools import (
    deposit_clip_to_dropbox,
    get_broll_tools,
)
from packages.integrations.context import current_supabase


# ── Structured output schema ──────────────────────────────────────────────
# Doubles as the JSON contract the frontend can render as a "b-roll plan" card.
# `draft_scripts` fills it via ChatAnthropic.with_structured_output(BRollPlan).
class BRollScript(BaseModel):
    prompt: str = Field(
        description="The b-roll scene to render — a vivid, self-contained "
        "description of one interrupt-style moment (slapstick, a sports miss, "
        "a funny interruption, a dramatic beat)."
    )
    aspect_ratio: str = Field(
        default="16:9",
        description="'16:9' for landscape (primary) or '9:16' for portrait "
        "(YouTube Shorts).",
    )
    duration_seconds: int = Field(
        default=6,
        description="Clip length in seconds, short and flexible (~5–10).",
    )
    topic: str = Field(
        description="The topic/theme this clip belongs to — used to organize "
        "the Dropbox folder (e.g. 'Conservative-Commentary')."
    )
    rationale: str = Field(
        default="",
        description="One line on why this clip fits the topic / direction.",
    )


class BRollPlan(BaseModel):
    title: str = Field(description="Short title for this batch, e.g. 'B-roll — June 15 batch'.")
    summary: str = Field(description="1–3 sentence overview of the batch and its angle.")
    clips: list[BRollScript] = Field(
        default_factory=list,
        description="The list of b-roll clips to generate.",
    )


# ── Extended state ────────────────────────────────────────────────────────
class BRollState(BaseAgentState):
    """Extends BaseAgentState with intent routing + the structured plan."""
    intent: str | None        # "draft_broll" | "generate_broll" | "general"
    plan: dict | None          # BRollPlan.model_dump(), surfaced for the frontend


class BRollAgent(BaseAgent):
    slug = "broll"
    name = "B-Roll Producer"
    description = (
        "Writes original b-roll scripts from your topics and weekly direction, "
        "generates short interrupt-style clips with Higgsfield (landscape + "
        "Shorts), and files them in your Dropbox organized by date and topic."
    )
    # Sonnet for scripting quality — writing punchy, on-tone b-roll prompts is
    # creative work, not a simple transform.
    model = "claude-sonnet-4-6"

    def get_structured_outputs(self, state: dict, visited_nodes: list[str]) -> dict[str, dict]:
        """Surface the BRollPlan as a structured frontend card — but only when
        `draft_scripts` actually ran this turn. The plan persists on state
        across turns (LangGraph checkpointer), so gating on visited_nodes
        prevents re-rendering the same card on follow-ups."""
        out: dict[str, dict] = {}
        if "draft_scripts" in visited_nodes and state.get("plan"):
            out["plan"] = state["plan"]
        return out

    def __init__(self):
        self.llm = ChatAnthropic(model=self.model)
        self.tools = get_broll_tools()
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(BRollState)

        graph.add_node("load_profile", self._load_profile_node)
        # peer_context: latest Strategist brief etc. — lets the drafted b-roll
        # ride the same angle the channel is already planning.
        graph.add_node("load_peer_context", self._load_peer_context_node)
        graph.add_node("classify_intent", self._classify_intent_node)

        graph.add_node("draft_scripts", self._draft_scripts_node)
        graph.add_node("persist_script", self._persist_script_node)
        graph.add_node("generate_clips", self._generate_clips_node)
        graph.add_node("organize_dropbox", self._organize_dropbox_node)
        graph.add_node("set_direction", self._set_direction_node)
        graph.add_node("general_answer", self._general_answer_node)
        graph.add_node("respond", self._respond_node)

        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "load_peer_context")
        graph.add_edge("load_peer_context", "classify_intent")

        graph.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
            {
                "draft_broll": "draft_scripts",
                "generate_broll": "generate_clips",
                "set_direction": "set_direction",
                "general": "general_answer",
            },
        )
        graph.add_edge("set_direction", "respond")

        # Drafting path: write the plan, file it, reply.
        graph.add_edge("draft_scripts", "persist_script")
        graph.add_edge("persist_script", "respond")
        # Generation path: render the clips, deposit to Dropbox, reply.
        graph.add_edge("generate_clips", "organize_dropbox")
        graph.add_edge("organize_dropbox", "respond")
        graph.add_edge("general_answer", "respond")
        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: BRollState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    def _peer_context(self, state: BRollState) -> dict:
        return (state.get("metadata") or {}).get("peer_context") or {}

    def _last_human_message(self, state: BRollState) -> HumanMessage | None:
        return next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )

    def _last_user_text(self, state: BRollState) -> str:
        last = self._last_human_message(state)
        if last is None:
            return ""
        return last.content if isinstance(last.content, str) else str(last.content)

    def _render_plan(self, state: BRollState, plan: dict) -> str:
        """Render a BRollPlan dict to clean Markdown via broll_plan.j2. One
        render shared by the chat reply and the Storage export so they never
        drift."""
        return render(
            "broll",
            "broll_plan.j2",
            profile=self._profile(state),
            plan=plan,
        ).rstrip() + "\n"

    # ── Routers ────────────────────────────────────────────────────────────
    def _route_by_intent(self, state: BRollState) -> str:
        intent = (state.get("intent") or "general").lower()
        if intent not in {"draft_broll", "generate_broll", "set_direction", "general"}:
            return "general"
        return intent

    # ── Nodes ──────────────────────────────────────────────────────────────
    async def _load_profile_node(self, state: BRollState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    async def _classify_intent_node(self, state: BRollState):
        profile = self._profile(state)
        prompt = render("broll", "classify.j2", profile=profile)
        # `marcus:silent` keeps the bare-slug classifier response out of chat.
        response = await self.llm.with_config(tags=["marcus:silent"]).ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=self._last_user_text(state)),
        ])
        raw = response.content.strip().strip("`").lower()
        intent = raw if raw in {"draft_broll", "generate_broll", "set_direction", "general"} else "general"
        return {"intent": intent}

    async def _draft_scripts_node(self, state: BRollState):
        """Write a batch of b-roll prompts from the topics + weekly direction.

        Pure LLM with structured output — no Higgsfield key required. The
        user's message carries the topics/direction (the weekly direction is
        fed in as text); we turn it into a BRollPlan the frontend can render
        and the generation path can consume.
        """
        profile = self._profile(state)
        system_prompt = render(
            "broll",
            "draft_scripts.j2",
            profile=profile,
            peer_context=self._peer_context(state),
        )
        structured_llm = self.llm.with_structured_output(BRollPlan)
        plan: BRollPlan = await structured_llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=self._last_user_text(state)),
        ])
        return {"plan": plan.model_dump(mode="json")}

    async def _persist_script_node(self, state: BRollState):
        """Best-effort export of the plan Markdown to Storage as kind="script".

        Mirrors the other agents' artifact export: the structured object
        already streams to the frontend; this drops a human-readable copy into
        the org-assets bucket. No-op in dev mode and on any storage error —
        never breaks the user-facing reply.
        """
        plan = state.get("plan")
        org_id = state.get("org_id") or ""
        supabase = current_supabase.get()
        if not plan or supabase is None or not _is_real_uuid(org_id):
            return {}

        from datetime import datetime, timezone
        from packages.agents.core.storage_export import export_to_storage

        md_body = self._render_plan(state, plan)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        await export_to_storage(
            org_id=org_id,
            agent_slug=self.slug,
            kind="script",
            filename=f"broll-plan-{ts}.md",
            content=md_body,
            mime_type="text/markdown",
            tags=["b-roll", "script"],
        )
        return {}

    async def _generate_clips_node(self, state: BRollState):
        """Submit the drafted prompts to Higgsfield and collect rendered clips.

        Degrades gracefully: if no HIGGSFIELD_API_KEY is set the client raises
        HiggsfieldUnavailable, which we catch once and report as a clear status
        message — no clips are produced, the run does not crash. Re-running a
        bad clip means calling this again (the agent can be asked to regenerate
        a specific clip with a tweaked prompt).

        Generated clips (URL + bytes) are stashed on state.metadata.clips for
        the organize_dropbox node.
        """
        from packages.integrations.higgsfield import (
            HiggsfieldUnavailable,
            HiggsfieldError,
            is_configured,
            generate_clip,
        )

        plan = state.get("plan") or {}
        clips_spec = plan.get("clips") or []
        existing_meta = state.get("metadata") or {}

        if not clips_spec:
            return {
                "messages": [AIMessage(content=(
                    "I don't have a b-roll plan to generate from yet. Ask me to "
                    "draft b-roll for a topic first, then I'll render the clips."
                ))]
            }

        if not is_configured():
            return {
                "messages": [AIMessage(content=(
                    "Video generation isn't configured yet — there's no Higgsfield "
                    "API key set, so I can't render clips. The b-roll scripts are "
                    "ready to go the moment the key is added."
                ))]
            }

        rendered: list[dict] = []
        errors: list[str] = []
        for spec in clips_spec:
            try:
                clip = await generate_clip(
                    spec.get("prompt", ""),
                    aspect_ratio=spec.get("aspect_ratio", "16:9"),
                    duration_seconds=int(spec.get("duration_seconds", 6)),
                    download=True,
                )
            except HiggsfieldUnavailable as e:
                # Lost the key mid-batch (or env changed) — stop cleanly.
                errors.append(str(e))
                break
            except HiggsfieldError as e:
                errors.append(f"{spec.get('prompt', '')[:40]}…: {e}")
                continue
            import base64
            rendered.append({
                "topic": spec.get("topic", "misc"),
                "aspect_ratio": clip.aspect_ratio,
                "duration_seconds": clip.duration_seconds,
                "url": clip.url,
                "bytes_b64": base64.b64encode(clip.bytes_).decode() if clip.bytes_ else None,
            })

        return {
            "metadata": {
                **existing_meta,
                "clips": rendered,
                "clip_errors": errors,
            }
        }

    async def _organize_dropbox_node(self, state: BRollState):
        """Deposit rendered clips into Dropbox organized by date & topic.

        Files each clip under /B-Roll/<date>/<topic>/. Best-effort: a missing
        Dropbox connection or upload error is reported but never crashes the
        run. Builds a status summary for the reply.
        """
        import base64

        meta = state.get("metadata") or {}
        rendered = meta.get("clips") or []
        org_id = state.get("org_id") or ""

        if not rendered:
            # generate_clips already produced an AIMessage (no key / no plan).
            return {}

        deposited: list[str] = []
        for clip in rendered:
            b64 = clip.get("bytes_b64")
            if not b64:
                continue
            path = await deposit_clip_to_dropbox(
                org_id,
                filename=f"{clip.get('aspect_ratio', '16-9').replace(':', '-')}-clip.mp4",
                clip_bytes=base64.b64decode(b64),
                topic=clip.get("topic", "misc"),
            )
            if path:
                deposited.append(path)

        n = len(rendered)
        if deposited:
            paths = "\n".join(f"- {p}" for p in deposited)
            msg = f"Rendered {n} clip(s) and filed {len(deposited)} into Dropbox:\n{paths}"
        else:
            msg = (
                f"Rendered {n} clip(s). Dropbox isn't connected (or the upload "
                "didn't go through), so they weren't filed — connect Dropbox to "
                "auto-organize them by date and topic."
            )
        return {"messages": [AIMessage(content=msg)]}

    async def _set_direction_node(self, state: BRollState):
        """Save the week's creative direction for the automated daily batches.

        The message text IS the direction ("this week's direction: pro-America
        angles, sarcasm..."). Stored on agents.config (broll row) under
        `weekly_direction`, which the daily production run
        (apps/api/app/services/broll_production.py) reads every morning.
        Read-modify-write so sibling config keys (daily_clip_target, aspect
        ratio, daily_production_enabled) survive."""
        import re
        from datetime import datetime, timezone

        raw = self._last_user_text(state)
        # Strip a leading "this week's direction:"-style preamble if present.
        direction = re.sub(
            r"^\s*(?:this week'?s?|the|update(?:\s+the)?|set(?:\s+the)?)?\s*"
            r"(?:b-?roll\s+)?direction(?:\s+(?:is|to|:))?\s*[:\-]?\s*",
            "", raw, flags=re.IGNORECASE,
        ).strip() or raw.strip()

        org_id = state.get("org_id") or ""
        supabase = current_supabase.get()
        saved = False
        if supabase is not None and _is_real_uuid(org_id) and direction:
            try:
                resp = (
                    supabase.table("agents")
                    .select("config")
                    .eq("org_id", org_id)
                    .eq("slug", self.slug)
                    .limit(1)
                    .execute()
                )
                config = (resp.data[0].get("config") if resp.data else None) or {}
                config["weekly_direction"] = direction[:2000]
                config["direction_updated_at"] = datetime.now(timezone.utc).isoformat()
                resp = supabase.table("agents").update({"config": config}).eq(
                    "org_id", org_id
                ).eq("slug", self.slug).execute()
                # A zero-row update (agent row missing) must not report
                # success. Note: this is a whole-column write, so it can
                # race a concurrent PATCH /agents/broll/config — last
                # writer wins; acceptable for a weekly, human-paced value.
                saved = bool(resp.data)
            except Exception as e:
                print(f"[broll] weekly_direction save failed: {e!r}", flush=True)

        if saved:
            msg = (
                f"Locked in for the week: **{direction[:400]}**\n\n"
                "Every daily batch will draft against this until you update it. "
                "You can still steer any single batch in chat ('draft b-roll "
                "about X, lighter tone') without changing the weekly direction."
            )
        else:
            msg = (
                f"Got the direction — **{direction[:400]}** — but I couldn't "
                "persist it (no workspace connection), so the daily batches "
                "won't pick it up yet. I'll still use it for anything you ask "
                "me to draft right now."
            )
        return {"messages": [AIMessage(content=msg)]}

    async def _general_answer_node(self, state: BRollState):
        """Free-form text answer for the general intent."""
        profile = self._profile(state)
        system_prompt = render(
            "broll",
            "system.j2",
            profile=profile,
            intent="general",
            peer_context=self._peer_context(state),
        )
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}

    async def _respond_node(self, state: BRollState):
        plan = state.get("plan")
        # If the generation/organize path produced a status AIMessage, surface
        # it (and don't also dump the plan markdown on top).
        last = state["messages"][-1] if state["messages"] else None
        if isinstance(last, AIMessage) and last.content and "draft" not in (state.get("intent") or ""):
            return {"messages": [AIMessage(content=last.content)]}

        if plan:
            return {"messages": [AIMessage(content=self._render_plan(state, plan))]}

        last_ai = next(
            (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.content),
            None,
        )
        content = (last_ai.content if last_ai else "") or "Done."
        return {"messages": [AIMessage(content=content)]}
