from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from pydantic import BaseModel, Field
from typing import Literal

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.peer_context import _is_real_uuid
from packages.agents.core.templates import render
from packages.agents.strategist.tools import get_strategist_tools
from packages.integrations.context import current_supabase


def _priority_from_confidence(confidence: str | None) -> str:
    """Map the Strategist's idea confidence onto the workspace's task
    priority axis. High-confidence ideas show up as high-priority To-Dos
    (red border on the Kanban card) so they catch the user's eye first.
    Anything we don't recognize falls to medium."""
    if confidence == "high":
        return "high"
    if confidence == "low":
        return "low"
    return "medium"


# ── Structured output schema ──────────────────────────────────────────────
# Pydantic models here double as the JSON contract the frontend can render.
# `compose_brief` fills this via ChatAnthropic.with_structured_output(WeeklyBrief).
class VideoIdea(BaseModel):
    title: str = Field(description="Scroll-stopping title, under 60 characters, in the creator's voice.")
    hook: str = Field(description="First 10 seconds of the video, one sentence.")
    why_now: str = Field(description="The specific data point or trend that justifies this idea.")
    confidence: Literal["high", "medium", "low"] = Field(description="Confidence level.")
    rationale: str = Field(description="One-line reason for the confidence level.")
    citations: list[str] = Field(
        default_factory=list,
        description="1–3 short strings pulled from the research (trend name, competitor title, metric).",
    )


class WeeklyBrief(BaseModel):
    headline: str = Field(description="One sentence summarizing the week's strategic take.")
    ideas: list[VideoIdea] = Field(description="3–5 ranked video ideas, ordered best-first.")


# ── Extended state ────────────────────────────────────────────────────────
class StrategistState(BaseAgentState):
    """Extends BaseAgentState with intent routing and structured brief output."""
    intent: str | None       # "weekly_brief" | "script_outline" | "research"
    brief: dict | None       # WeeklyBrief.model_dump(), surfaced for the frontend


class StrategistAgent(BaseAgent):
    slug = "strategist"
    name = "Strategist"
    description = (
        "Decides what to make next. Pulls channel analytics and niche trends, "
        "ranks video ideas, drafts scripts and hooks."
    )
    model = "claude-sonnet-4-6"
    # Long-term memory: the Strategist remembers what it recommended and what
    # the creator reacted to across sessions, so briefs build on the running
    # relationship rather than starting cold each week. See core/memory.py.
    memory_enabled = True

    def get_structured_outputs(self, state: dict, visited_nodes: list[str]) -> dict[str, dict]:
        """Surface the WeeklyBrief as a structured frontend card — but ONLY
        when `compose_brief` actually ran this turn. The brief field stays
        on state across turns (LangGraph checkpointer persists it), so
        gating on visited_nodes prevents the same card from re-rendering
        on every follow-up message that doesn't regenerate the brief."""
        out: dict[str, dict] = {}
        if "compose_brief" in visited_nodes and state.get("brief"):
            out["brief"] = state["brief"]
        return out

    def __init__(self):
        self.tools = get_strategist_tools()
        # Tool-bound LLM for the ReAct loop.
        self.llm_with_tools = ChatAnthropic(model=self.model).bind_tools(self.tools)
        self.tool_node = ToolNode(self.tools)
        # Plain LLM (no tools) for intent classification + structured brief composition.
        self.llm = ChatAnthropic(model=self.model)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(StrategistState)

        graph.add_node("load_profile", self._load_profile_node)
        # peer_context: latest brief / package / etc. for this org. Even the
        # Strategist reads it so a repeat brief can build on what was said
        # last time rather than starting cold.
        graph.add_node("load_peer_context", self._load_peer_context_node)
        # load_memory: recall the most relevant snippets from past sessions
        # (state.metadata.memories), parallel to peer_context. Best-effort —
        # empty list in dev mode / without an embedding backend.
        graph.add_node("load_memory", self._load_memory_node)
        graph.add_node("classify_intent", self._classify_intent_node)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self.tool_node)
        graph.add_node("compose_brief", self._compose_brief_node)
        # persist_brief writes the just-composed WeeklyBrief into Postgres so
        # peer agents (Brand Manager, Publisher, CM) can hydrate it on their
        # next run. No-op in dev mode (no Supabase) — see implementation.
        graph.add_node("persist_brief", self._persist_brief_node)
        graph.add_node("respond", self._respond_node)

        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "load_peer_context")
        graph.add_edge("load_peer_context", "load_memory")
        graph.add_edge("load_memory", "classify_intent")
        graph.add_edge("classify_intent", "agent")

        # The ReAct loop exits three ways:
        #   - more tool calls pending   -> tools
        #   - no tool calls + weekly_brief intent -> compose_brief (structured)
        #   - no tool calls + anything else        -> respond (free-form)
        graph.add_conditional_edges(
            "agent",
            self._after_agent,
            {
                "tools": "tools",
                "compose_brief": "compose_brief",
                "respond": "respond",
            },
        )
        graph.add_edge("tools", "agent")
        graph.add_edge("compose_brief", "persist_brief")
        graph.add_edge("persist_brief", "respond")
        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: StrategistState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    def _peer_context(self, state: StrategistState) -> dict:
        return (state.get("metadata") or {}).get("peer_context") or {}

    def _memories(self, state: StrategistState) -> list[dict]:
        """Recalled long-term memories, hydrated by the load_memory node.
        Empty list in dev mode / without an embedding backend."""
        return (state.get("metadata") or {}).get("memories") or []

    def _last_user_text(self, state: StrategistState) -> str:
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        return last_human.content if last_human else ""

    # ── Node: load per-tenant profile into state.metadata ─────────────────
    async def _load_profile_node(self, state: StrategistState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    # ── Node: classify user intent ─────────────────────────────────────────
    async def _classify_intent_node(self, state: StrategistState):
        profile = self._profile(state)
        prompt = render("strategist", "classify.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=self._last_user_text(state)),
        ])
        raw = response.content.strip().strip("`").lower()
        # Accept the exact slug or fall back to research for anything unexpected.
        intent = raw if raw in {"weekly_brief", "script_outline", "research"} else "research"
        return {"intent": intent}

    # ── Node: ReAct LLM step (system prompt is intent-aware) ──────────────
    async def _agent_node(self, state: StrategistState):
        profile = self._profile(state)
        system_prompt = render(
            "strategist",
            "system.j2",
            profile=profile,
            intent=state.get("intent") or "research",
            peer_context=self._peer_context(state),
            memories=self._memories(state),
        )
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await self.llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    # ── Router after the ReAct agent step ─────────────────────────────────
    def _after_agent(self, state: StrategistState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        if (state.get("intent") or "research") == "weekly_brief":
            return "compose_brief"
        return "respond"

    # ── Node: structured brief composition ────────────────────────────────
    async def _compose_brief_node(self, state: StrategistState):
        profile = self._profile(state)

        # Collect everything the ReAct loop gathered — tool outputs plus the
        # LLM's most recent free-form take — so the composer has the full
        # context to distill.
        tool_outputs: list[str] = []
        for m in state["messages"]:
            if isinstance(m, ToolMessage):
                name = getattr(m, "name", "tool")
                tool_outputs.append(f"[{name}]\n{m.content}")
        last_ai = next(
            (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.content),
            None,
        )

        context = (
            f"USER REQUEST:\n{self._last_user_text(state)}\n\n"
            f"RESEARCH GATHERED:\n"
            + ("\n\n".join(tool_outputs) if tool_outputs else "(none)")
            + "\n\nDRAFT TAKE FROM THE STRATEGIST:\n"
            + (last_ai.content if last_ai else "(none)")
        )

        structured_llm = self.llm.with_structured_output(WeeklyBrief)
        prompt = render(
            "strategist",
            "compose_brief.j2",
            profile=profile,
            peer_context=self._peer_context(state),
        )
        brief: WeeklyBrief = await structured_llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        return {"brief": brief.model_dump(mode="json")}

    # ── Node: persist the brief so peers can read it ──────────────────────
    async def _persist_brief_node(self, state: StrategistState):
        """Write the just-composed brief to strategist_briefs AND drop one
        task per ranked idea into the user's workspace.

        No-op when:
          - Supabase isn't configured (local dev)
          - org_id isn't a real UUID (dev fallback)
          - the brief field is empty (defensive — should never happen here
            because this node only runs after compose_brief)
        Errors are swallowed: a failed persistence shouldn't break the user-
        facing reply. Logs are the trail; the orchestrator already streams
        the brief object directly to the frontend regardless.

        The auto-created tasks are how the brief loops back into action —
        each idea becomes a To-Do the user sees on /app/tasks. Without
        this they'd have to re-type each idea by hand.
        """
        brief = state.get("brief")
        org_id = state.get("org_id") or ""
        thread_id = state.get("thread_id") or ""
        supabase = current_supabase.get()
        if not brief or supabase is None or not _is_real_uuid(org_id):
            return {}

        # ── Step 1: persist the brief itself ─────────────────────────────
        brief_payload = {
            "org_id": org_id,
            "thread_id": thread_id if _is_real_uuid(thread_id) else None,
            "headline": brief.get("headline", ""),
            "ideas": brief.get("ideas", []),
        }
        brief_id: str | None = None
        try:
            result = supabase.table("strategist_briefs").insert(brief_payload).execute()
            if result.data:
                brief_id = result.data[0].get("id")
        except Exception:
            # Persistence is best-effort. Don't fail the run on it.
            pass

        # ── Step 1b: drop a Markdown copy into Storage Library ───────────
        # The DB row above is the structured form (peer agents read it).
        # The Markdown export is the human-readable form the creator can
        # reopen from /app/storage and share. Same render the chat uses
        # in _respond_node — kept literal here so the file matches what
        # the creator already saw.
        from packages.agents.core.storage_export import export_to_storage
        from datetime import datetime, timezone

        md_lines = [f"# {brief.get('headline', 'Weekly brief')}", ""]
        for i, idea in enumerate(brief.get("ideas") or [], 1):
            md_lines.append(f"## {i}. {idea.get('title', '')}".rstrip())
            if idea.get("hook"):
                md_lines.append(f"**Hook:** {idea['hook']}")
            if idea.get("why_now"):
                md_lines.append(f"**Why now:** {idea['why_now']}")
            if idea.get("confidence"):
                md_lines.append(
                    f"**Confidence:** {idea['confidence']}"
                    + (f" — {idea['rationale']}" if idea.get("rationale") else "")
                )
            if idea.get("citations"):
                md_lines.append(f"*Cites:* {'; '.join(idea['citations'])}")
            md_lines.append("")
        md_body = "\n".join(md_lines).rstrip() + "\n"
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await export_to_storage(
            org_id=org_id,
            agent_slug=self.slug,
            kind="brief",
            filename=f"weekly-brief-{ts}.md",
            content=md_body,
            mime_type="text/markdown",
            source_id=brief_id,
            tags=["weekly-brief"],
        )

        # ── Step 1c: polished PDF — archived in Storage + delivered to Dropbox.
        # Both best-effort and non-blocking: the brief object already streamed
        # to the frontend and the Markdown copy is already filed. A PDF render
        # error or a missing Dropbox connection must not fail the run.
        from packages.agents.core.pdf_export import (
            deliver_pdf_to_dropbox,
            render_pdf,
        )
        from packages.agents.core.storage_export import export_pdf_to_storage

        brand_name = self._profile(state).brand.name
        headline = brief.get("headline", "Weekly brief")
        pdf_filename = f"weekly-brief-{ts}.pdf"
        try:
            await export_pdf_to_storage(
                org_id=org_id,
                agent_slug=self.slug,
                kind="brief",
                filename=pdf_filename,
                title="Weekly Brief",
                subtitle=headline,
                brand_name=brand_name,
                markdown_body=md_body,
                source_id=brief_id,
                tags=["weekly-brief"],
            )
            pdf_bytes = render_pdf(
                "Weekly Brief", md_body, subtitle=headline, brand_name=brand_name
            )
            await deliver_pdf_to_dropbox(
                org_id,
                filename=pdf_filename,
                pdf_bytes=pdf_bytes,
                subfolder="briefs",
            )
        except Exception as e:
            print(f"[strategist] brief PDF export/delivery failed: {e!r}", flush=True)

        # ── Step 2: spawn one task per ranked idea ───────────────────────
        # Each idea becomes a To-Do so the user can move it across the
        # /app/tasks Kanban as they work through the week. Body of the
        # task carries the hook + why_now so the user has context without
        # opening the brief.
        from packages.agents.core.tasks import create_tasks_from_agent

        ideas = brief.get("ideas", []) or []
        items = []
        for i, idea in enumerate(ideas):
            title = (idea.get("title") or "").strip()
            if not title:
                continue
            hook = (idea.get("hook") or "").strip()
            why_now = (idea.get("why_now") or "").strip()
            description = "\n\n".join(
                part for part in (
                    f"Hook: {hook}" if hook else "",
                    f"Why now: {why_now}" if why_now else "",
                ) if part
            ) or None
            items.append({
                "title": title,
                "description": description,
                "priority": _priority_from_confidence(idea.get("confidence")),
                "status": "todo",
                "metadata": {
                    "source": "strategist_brief",
                    "brief_id": brief_id,
                    "idea_index": i,
                    "confidence": idea.get("confidence"),
                },
            })

        if items:
            await create_tasks_from_agent(
                org_id=org_id,
                agent_slug=self.slug,
                items=items,
            )

        return {}

    # ── Node: terminal respond ────────────────────────────────────────────
    async def _respond_node(self, state: StrategistState):
        brief = state.get("brief")
        if brief:
            # Render a human-readable markdown view of the structured brief.
            # The structured object is still on state["brief"] for the frontend.
            lines = [f"# {brief['headline']}", ""]
            for i, idea in enumerate(brief.get("ideas", []), 1):
                lines.append(f"## {i}. {idea['title']}")
                lines.append(f"**Hook:** {idea['hook']}")
                lines.append(f"**Why now:** {idea['why_now']}")
                lines.append(
                    f"**Confidence:** {idea['confidence']} — {idea['rationale']}"
                )
                if idea.get("citations"):
                    lines.append(f"*Cites:* {'; '.join(idea['citations'])}")
                lines.append("")
            content = "\n".join(lines).rstrip()
        else:
            # Research / script_outline paths — surface the ReAct loop's last
            # assistant message as the reply.
            last_ai = next(
                (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.content),
                None,
            )
            content = (last_ai.content if last_ai else "") or "Done."
        # Persist a concise summary of this turn to long-term memory so the
        # next session can build on it. Best-effort — no-ops without Supabase /
        # an embedding backend (see core/memory.py).
        self._persist_turn_memory_background(state, takeaway=content)
        return {"messages": [AIMessage(content=content)]}
