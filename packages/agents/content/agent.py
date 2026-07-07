"""
Content Agent (Agent #5, "Force Multiplier") — turns every new YouTube upload
into a full repurposed content drop: extracted podcast audio, short clips, a
drafted podcast episode with chapters, a two-step review queue, and (once
approved) cross-platform publishing.

Two ways in:

  scheduler  — the YouTube new-upload poller (apps/api/app/services/
               scheduler.py) dispatches a run with intent="run_pipeline" +
               video_id preset the moment an upload is detected. This is the
               primary, fully-automatic path.
  chat       — the team can ask for pipeline status, process a specific video
               by link, or ask general questions.

Three intents:

  run_pipeline    — drive one video through the stage sequence. Every stage
                    writes its outcome to the durable `content_pipelines`
                    ledger row (packages/agents/content/tools.py), so
                    progress survives restarts and is dashboard-readable
                    without touching LangGraph checkpoints.
  pipeline_status — answer "where's today's content?" from the ledger.
  general         — everything else.

Graph shape:

  START → load_profile → load_peer_context → classify_intent
                                                  ↓
              ┌───────────────────────────────────┼─────────────────────┐
          run_pipeline                     pipeline_status           general
              ↓                                   ↓                     ↓
          init_pipeline ──(no video)──┐      status_answer       general_answer
              ↓                       │           │                     │
          extract_audio               │           │                     │
              ↓                       │           │                     │
          generate_clips              │           │                     │
              ↓                       │           │                     │
          draft_podcast               │           │                     │
              ↓                       ▼           ▼                     ▼
          queue_review ──────────► respond ◄─────────────────────────────

Phase A ships the trigger, the ledger, and this graph skeleton. The three
generation stages (extract_audio / generate_clips / draft_podcast) are
recorded-but-stubbed: each writes a "skipped — not yet implemented" stage
entry so the ledger is honest about what ran. Phase B fills in the media
work (audio extraction, Opus Clip, podcast drafting); Phase C adds the
Monday.com review queue + the reviewer→owner approval chain (declared in
manifest.json already); Phase D adds the publish fan-out behind that gate.
"""
from __future__ import annotations

import re

from langgraph.graph import StateGraph, END, START
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.agents.content.tools import (
    fetch_recent_pipelines,
    get_content_tools,
    record_stage,
    set_pipeline_status,
    upsert_pipeline_row,
)

VALID_INTENTS = {"run_pipeline", "pipeline_status", "general"}

# The generation stages, in execution order. Phase A stubs them; each later
# phase replaces a stub with the real implementation without reshaping the
# graph (the ledger schema and node names are the stable contract).
STUBBED_STAGES: dict[str, str] = {
    "extract_audio": "audio extraction ships in Phase B",
    "generate_clips": "clip generation (Opus Clip) ships in Phase B",
    "draft_podcast": "podcast episode drafting ships in Phase B",
}

# Matches the 11-char video id out of the common YouTube URL shapes. No bare
# 11-char fallback on purpose — ordinary words ("consistency") are 11 chars.
_YT_URL_ID = re.compile(r"(?:youtu\.be/|v=|shorts/|live/|embed/)([A-Za-z0-9_-]{11})")


class ContentState(BaseAgentState):
    """Extends BaseAgentState with intent routing + the pipeline ledger row."""
    intent: str | None       # "run_pipeline" | "pipeline_status" | "general"
    video_id: str | None     # preset by the scheduler; parsed from chat otherwise
    video_title: str | None
    pipeline: dict | None    # mirror of the content_pipelines row, for the FE card


class ContentAgent(BaseAgent):
    slug = "content"
    name = "Content Agent"
    description = (
        "Turns every new YouTube upload into a full content drop: extracts "
        "podcast audio, generates short clips, drafts the podcast episode "
        "with chapters, queues everything for two-step review, and publishes "
        "approved assets across platforms."
    )
    model = "claude-sonnet-4-6"

    def get_structured_outputs(self, state: dict, visited_nodes: list[str]) -> dict[str, dict]:
        """Surface the pipeline ledger as a structured frontend card when a
        pipeline was actually initialized this run (gating on visited_nodes so
        follow-up turns don't re-render a stale card)."""
        out: dict[str, dict] = {}
        if "init_pipeline" in visited_nodes and state.get("pipeline"):
            out["pipeline"] = state["pipeline"]
        return out

    def __init__(self):
        self.llm = ChatAnthropic(model=self.model)
        self.tools = get_content_tools()
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(ContentState)

        graph.add_node("load_profile", self._load_profile_node)
        graph.add_node("load_peer_context", self._load_peer_context_node)
        graph.add_node("classify_intent", self._classify_intent_node)

        graph.add_node("init_pipeline", self._init_pipeline_node)
        graph.add_node("extract_audio", self._extract_audio_node)
        graph.add_node("generate_clips", self._generate_clips_node)
        graph.add_node("draft_podcast", self._draft_podcast_node)
        graph.add_node("queue_review", self._queue_review_node)

        graph.add_node("status_answer", self._status_answer_node)
        graph.add_node("general_answer", self._general_answer_node)
        graph.add_node("respond", self._respond_node)

        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "load_peer_context")
        graph.add_edge("load_peer_context", "classify_intent")

        graph.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
            {
                "run_pipeline": "init_pipeline",
                "pipeline_status": "status_answer",
                "general": "general_answer",
            },
        )

        # Pipeline lane: only proceed past init when a video was resolved.
        graph.add_conditional_edges(
            "init_pipeline",
            self._route_after_init,
            {"proceed": "extract_audio", "abort": "respond"},
        )
        graph.add_edge("extract_audio", "generate_clips")
        graph.add_edge("generate_clips", "draft_podcast")
        graph.add_edge("draft_podcast", "queue_review")
        graph.add_edge("queue_review", "respond")

        graph.add_edge("status_answer", "respond")
        graph.add_edge("general_answer", "respond")
        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: ContentState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    def _peer_context(self, state: ContentState) -> dict:
        return (state.get("metadata") or {}).get("peer_context") or {}

    def _last_user_text(self, state: ContentState) -> str:
        last = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        if last is None:
            return ""
        return last.content if isinstance(last.content, str) else str(last.content)

    def _render_system(self, state: ContentState, intent: str) -> str:
        """system.j2 with every StrictUndefined-required variable supplied.

        podcast_brand / publish_deadline_local come from per-org agent config
        eventually (manifest config_schema declares them); Phase A renders
        with neutral defaults.
        """
        return render(
            "content",
            "system.j2",
            profile=self._profile(state),
            intent=intent,
            peer_context=self._peer_context(state),
            podcast_brand="",
            publish_deadline_local="12:00",
        )

    # ── Routers ────────────────────────────────────────────────────────────
    def _route_by_intent(self, state: ContentState) -> str:
        intent = (state.get("intent") or "general").lower()
        return intent if intent in VALID_INTENTS else "general"

    def _route_after_init(self, state: ContentState) -> str:
        meta = state.get("metadata") or {}
        return "proceed" if meta.get("pipeline_ready") else "abort"

    # ── Shared nodes reused from BaseAgent: _load_peer_context_node ────────
    async def _load_profile_node(self, state: ContentState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    async def _classify_intent_node(self, state: ContentState):
        # Scheduler dispatches pre-set intent="run_pipeline" (+ video_id) —
        # keep it, exactly like Publisher's one-click actions.
        if state.get("intent"):
            return {}
        profile = self._profile(state)
        prompt = render("content", "classify.j2", profile=profile)
        try:
            response = await self.llm.with_config(tags=["marcus:silent"]).ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=self._last_user_text(state)),
            ])
            intent = response.content.strip().strip("`").lower()
        except Exception:
            intent = "general"
        if intent not in VALID_INTENTS:
            intent = "general"
        return {"intent": intent}

    # ── Pipeline lane ──────────────────────────────────────────────────────
    async def _init_pipeline_node(self, state: ContentState):
        """Resolve which video to process and open its ledger row.

        video_id arrives preset from the scheduler; for chat-initiated runs we
        parse a YouTube URL out of the message. No resolvable video → ask for
        the link and abort the lane (no ledger row is created).
        """
        existing_meta = state.get("metadata") or {}
        video_id = state.get("video_id")
        if not video_id:
            m = _YT_URL_ID.search(self._last_user_text(state))
            video_id = m.group(1) if m else None

        if not video_id:
            return {
                "metadata": {**existing_meta, "pipeline_ready": False},
                "messages": [AIMessage(content=(
                    "I need the video to process — paste the YouTube link "
                    "(watch, shorts, or live URL) and I'll run it through the "
                    "pipeline."
                ))],
            }

        org_id = state.get("org_id") or ""
        row = upsert_pipeline_row(
            org_id,
            video_id,
            video_title=state.get("video_title"),
            thread_id=state.get("thread_id"),
            status="processing",
        )
        # Dev mode (no Supabase) still runs the lane; the ledger is just absent.
        pipeline = row or {
            "video_id": video_id,
            "video_title": state.get("video_title"),
            "status": "processing",
            "stages": {},
            "assets": [],
            "error": None,
        }
        return {
            "video_id": video_id,
            "pipeline": pipeline,
            "metadata": {**existing_meta, "pipeline_ready": True},
        }

    async def _run_stubbed_stage(self, state: ContentState, stage: str):
        """Phase A: record the stage as skipped in the ledger — honestly, with
        the phase that implements it — and mirror it onto state.pipeline."""
        org_id = state.get("org_id") or ""
        video_id = state.get("video_id") or ""
        reason = STUBBED_STAGES[stage]
        record_stage(org_id, video_id, stage, "skipped", reason)
        pipeline = dict(state.get("pipeline") or {})
        stages = dict(pipeline.get("stages") or {})
        stages[stage] = {"status": "skipped", "detail": reason}
        pipeline["stages"] = stages
        return {"pipeline": pipeline}

    async def _extract_audio_node(self, state: ContentState):
        return await self._run_stubbed_stage(state, "extract_audio")

    async def _generate_clips_node(self, state: ContentState):
        return await self._run_stubbed_stage(state, "generate_clips")

    async def _draft_podcast_node(self, state: ContentState):
        return await self._run_stubbed_stage(state, "draft_podcast")

    async def _queue_review_node(self, state: ContentState):
        """Close out the run against the ledger.

        With assets: mark ready_for_review (Phase C turns this into Monday.com
        items + the reviewer→owner approval chain). Without assets — always
        the case while the generation stages are stubbed — mark failed with a
        plain-language error, so nothing sits in "processing" forever and the
        dashboard tells the truth about what happened.
        """
        org_id = state.get("org_id") or ""
        video_id = state.get("video_id") or ""
        pipeline = dict(state.get("pipeline") or {})
        assets = list(pipeline.get("assets") or [])

        if assets:
            set_pipeline_status(org_id, video_id, "ready_for_review", assets=assets)
            pipeline["status"] = "ready_for_review"
        else:
            error = (
                "no assets generated — the generation stages aren't "
                "implemented yet (Phase B)"
            )
            set_pipeline_status(org_id, video_id, "failed", error=error)
            pipeline["status"] = "failed"
            pipeline["error"] = error
        return {"pipeline": pipeline}

    # ── Chat lanes ─────────────────────────────────────────────────────────
    async def _status_answer_node(self, state: ContentState):
        """Answer status questions grounded in the ledger, not vibes: fetch
        the recent rows and hand them to the LLM as context."""
        rows = fetch_recent_pipelines(state.get("org_id") or "", limit=10)
        if rows:
            lines = []
            for r in rows:
                stages = ", ".join(
                    f"{name}={((v or {}).get('status'))}"
                    for name, v in (r.get("stages") or {}).items()
                ) or "no stages recorded"
                lines.append(
                    f"- {r.get('video_title') or r.get('video_id')} | "
                    f"status={r.get('status')} | {stages} | "
                    f"assets={len(r.get('assets') or [])} | "
                    f"error={r.get('error') or 'none'} | "
                    f"detected={r.get('detected_at')}"
                )
            data_block = "\n".join(lines)
        else:
            data_block = (
                "(no pipelines recorded yet — none have been triggered, or "
                "this is a dev environment without a database)"
            )
        system_prompt = self._render_system(state, "pipeline_status")
        response = await self.llm.ainvoke([
            SystemMessage(content=(
                system_prompt
                + "\n\n## Pipeline ledger (ground truth — answer ONLY from this)\n"
                + data_block
            )),
            *state["messages"],
        ])
        return {"messages": [response]}

    async def _general_answer_node(self, state: ContentState):
        system_prompt = self._render_system(state, "general")
        response = await self.llm.ainvoke(
            [SystemMessage(content=system_prompt)] + state["messages"]
        )
        return {"messages": [response]}

    async def _respond_node(self, state: ContentState):
        # Pipeline lane: render the ledger summary as the reply.
        if state.get("pipeline") and (state.get("intent") == "run_pipeline"):
            summary = render(
                "content",
                "pipeline_summary.j2",
                profile=self._profile(state),
                pipeline=state["pipeline"],
            ).rstrip() + "\n"
            return {"messages": [AIMessage(content=summary)]}

        last_ai = next(
            (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.content),
            None,
        )
        content = (last_ai.content if last_ai else "") or "Done."
        return {"messages": [AIMessage(content=content)]}
