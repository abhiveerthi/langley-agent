from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.message import add_messages
from typing import TypedDict, Annotated, Any
import json
import os
from pathlib import Path

import asyncio

from packages.agents.core.peer_context import load_peer_context
from packages.agents.core.memory import recall_memories, write_memory
from packages.integrations.context import current_supabase

# Strong refs to fire-and-forget turn-memory writes (asyncio keeps only
# weak refs). See BaseAgent._persist_turn_memory_background.
_memory_tasks: set[asyncio.Task] = set()


# Default single-step approval chain. One role labelled "approver" preserves
# the historical single-approver behaviour for every existing agent.
DEFAULT_APPROVAL_CHAIN: list[str] = ["approver"]


class BaseAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    org_id: str
    user_id: str
    thread_id: str
    task_id: str | None
    metadata: dict[str, Any]


class BaseAgent:
    slug: str = ""
    name: str = ""
    description: str = ""
    tools: list = []
    model: str = "claude-haiku-4-5-20251001"

    # Long-term memory opt-in. The conversational agents (Strategist, Brand
    # Manager, Community Manager) set this True and wire `load_memory` into
    # their graph + call `_persist_turn_memory` at run end. Default off so
    # one-shot / pipeline agents (Editor, Publisher, B-roll, …) don't pay the
    # embedding round-trip for memory they'd never recall. See core/memory.py.
    memory_enabled: bool = False

    def __init__(self):
        self._custom_checkpointer = None
        self.graph = self.build_graph()

    async def get_checkpointer(self):
        if self._custom_checkpointer is not None:
            return self._custom_checkpointer
        return AsyncPostgresSaver.from_conn_string(os.environ["DATABASE_URL"])

    async def compile(self):
        checkpointer = await self.get_checkpointer()
        return self.graph.compile(
            checkpointer=checkpointer,
            interrupt_before=self.interrupt_before_nodes,
        )

    @property
    def interrupt_before_nodes(self) -> list[str]:
        """Override to specify nodes that require human approval."""
        return []

    # ── Approval policy ────────────────────────────────────────────────────
    # `_approval_policy_cache` memoises the manifest read per class so we don't
    # re-open manifest.json on every gate hit. `None` until first read; the
    # sentinel `_MISSING` distinguishes "not yet read" from "read, none found".
    _approval_policy_cache: Any = None

    def _load_approval_policy(self) -> dict | None:
        """Read the optional `approval_policy` block from this agent's
        manifest.json (sits next to the agent module). Cached per instance.

        Shape (all optional):
            "approval_policy": {"approvers": ["reviewer", "owner"]}

        Returns None when there's no manifest, no policy block, or the file
        can't be parsed — callers fall back to the single-step default.
        """
        if self._approval_policy_cache is not None:
            return self._approval_policy_cache or None
        policy: dict | None = None
        try:
            module = __import__(self.__class__.__module__, fromlist=["__file__"])
            manifest_path = Path(module.__file__).parent / "manifest.json"
            if manifest_path.exists():
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                pol = data.get("approval_policy")
                if isinstance(pol, dict):
                    policy = pol
        except Exception:
            policy = None
        # Cache an empty dict to mark "already looked" without re-reading.
        self._approval_policy_cache = policy or {}
        return policy

    def approval_chain(self, state: dict) -> list[str]:
        """Return the ORDERED list of approver role labels required before the
        gated write executes.

        Default: a single step labelled "approver" — exactly today's behaviour
        (one approval → resume → write). Override (or declare an
        `approval_policy.approvers` list in manifest.json) to require a
        multi-step sequence, e.g. ["reviewer", "owner"]: each step must be
        approved IN ORDER; only the final approval resumes the graph.

        Receives the paused graph state so an agent can vary the chain by
        intent/lane if it ever needs to. The default ignores `state`.
        """
        policy = self._load_approval_policy()
        if policy:
            approvers = policy.get("approvers")
            if isinstance(approvers, list) and approvers:
                # Coerce to strings, drop blanks; fall back to default if empty.
                chain = [str(a) for a in approvers if str(a).strip()]
                if chain:
                    return chain
        return list(DEFAULT_APPROVAL_CHAIN)

    def build_graph(self) -> StateGraph:
        """Override to define the agent's graph."""
        raise NotImplementedError

    async def _load_peer_context_node(self, state: dict) -> dict:
        """Hydrate `state.metadata.peer_context` with the latest outputs of
        peer agents in the same org.

        Reusable across agents — wire it into your graph (typically right
        after `load_profile`) and the rendered prompts can reference
        `peer_context.latest_brief`, `peer_context.latest_package`, etc.
        Reads `current_supabase` and the state's `org_id`; gracefully
        no-ops in dev mode (returns empty PeerContext) so local runs work
        without Supabase configured. See packages/agents/core/peer_context.py.
        """
        org_id = state.get("org_id") or ""
        supabase = current_supabase.get()
        peer = await load_peer_context(org_id, supabase)
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "peer_context": peer.model_dump(mode="json"),
            }
        }

    async def _load_memory_node(self, state: dict) -> dict:
        """Hydrate `state.metadata["memories"]` with the most relevant past
        memories for this agent + org, recalled against the latest user turn.

        The long-term-memory analog of `_load_peer_context_node`: a best-effort
        async node wired in right after `load_peer_context`. Recalled snippets
        ride alongside `peer_context` in the rendered system prompt (templates
        guard on `memories is defined`). No-ops to an empty list when memory is
        off, Supabase isn't configured, the org isn't a real UUID, or no
        embedding backend is set — see core/memory.py. Pre-existing metadata is
        never clobbered.
        """
        existing_meta = state.get("metadata") or {}
        if not self.memory_enabled:
            return {"metadata": {**existing_meta, "memories": []}}

        query = self._last_user_text_for_memory(state)
        memories = await recall_memories(
            state.get("org_id") or "", self.slug, query, limit=5
        )
        return {"metadata": {**existing_meta, "memories": memories}}

    def _last_user_text_for_memory(self, state: dict) -> str:
        """Best-effort: the latest human message text, used as the recall query
        and (with the reply) the written summary. Tolerates LangChain message
        objects or plain dicts so this works for any agent's state shape."""
        for m in reversed(state.get("messages") or []):
            role = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else None)
            if role in ("human", "user"):
                content = getattr(m, "content", None)
                if content is None and isinstance(m, dict):
                    content = m.get("content")
                if content:
                    return content if isinstance(content, str) else str(content)
        return ""

    async def _persist_turn_memory(self, state: dict, takeaway: str | None = None) -> None:
        """Persist a concise summary of this turn to long-term memory.

        Call at the END of a run, after the user-facing output is produced.
        Writes "the creator asked X / the agent's key takeaway was Y" so future
        runs can recall the thread of the relationship. Best-effort: no-ops when
        memory is off / Supabase is absent / org isn't a real UUID / no
        embedding backend (see core/memory.py). Never raises into the run.

        `takeaway` lets an agent pass its own distilled summary (e.g. the last
        assistant message). When omitted we fall back to the latest assistant
        text in `state["messages"]`.
        """
        if not self.memory_enabled:
            return

        user_text = self._last_user_text_for_memory(state)
        if takeaway is None:
            takeaway = self._last_assistant_text_for_memory(state)
        user_text = (user_text or "").strip()
        takeaway = (takeaway or "").strip()
        if not user_text and not takeaway:
            return

        # Cap each side so a runaway reply doesn't bloat the embedded content.
        content = (
            f"User asked: {user_text[:1000]}\n"
            f"{self.name or self.slug} takeaway: {takeaway[:2000]}"
        ).strip()
        try:
            await write_memory(
                state.get("org_id"),
                self.slug,
                state.get("thread_id"),
                content,
                metadata={"thread_id": state.get("thread_id")},
            )
        except Exception as e:  # pragma: no cover - belt-and-suspenders
            print(f"[memory] _persist_turn_memory failed: {e!r}", flush=True)

    def _persist_turn_memory_background(
        self, state: dict, takeaway: str | None = None
    ) -> None:
        """Fire-and-forget `_persist_turn_memory` — for respond nodes.

        Awaiting the write inline puts an OpenAI embed + two Supabase
        round-trips (~0.4-1s) BETWEEN the finished answer and the
        user-visible reply (Slack posts only after the stream completes).
        The write is documented best-effort and reads its Supabase handle
        from a ContextVar the spawned task snapshots at creation, so
        detaching it is safe; the strong-ref set stops asyncio GC'ing it."""
        task = asyncio.create_task(
            self._persist_turn_memory(state, takeaway=takeaway)
        )
        _memory_tasks.add(task)
        task.add_done_callback(_memory_tasks.discard)

    def _last_assistant_text_for_memory(self, state: dict) -> str:
        """Latest assistant/AI message text — the fallback turn takeaway."""
        for m in reversed(state.get("messages") or []):
            role = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else None)
            if role in ("ai", "assistant"):
                content = getattr(m, "content", None)
                if content is None and isinstance(m, dict):
                    content = m.get("content")
                if content:
                    return content if isinstance(content, str) else str(content)
        return ""

    def get_approval_request(self, state: dict) -> dict | None:
        """Describe the action that is gated at an interrupt.

        Called by the API runtime when the graph is paused at one of
        `interrupt_before_nodes`. Returns the payload the frontend needs to
        render an approval card — or None if the agent has no HITL gates.

        Shape (matches the `approvals` table in migrations/001_core.sql):
            {
                "action_type":    "send_email" | "update_video_metadata" | ...,
                "action_payload": {...}   # arbitrary action-specific fields
                "preview":        "short human-readable summary for the card",
            }
        """
        return None

    def get_structured_outputs(
        self, state: dict, visited_nodes: list[str]
    ) -> dict[str, dict]:
        """Return per-run structured outputs the frontend should render as
        rich cards alongside the chat (Strategist's WeeklyBrief, eventually
        Publisher's package, etc.).

        The orchestrator calls this after `astream` finishes for a given
        run and emits one `structured_output` SSE event per (kind, data)
        entry. Default: nothing — agents that produce structured output
        override this. `visited_nodes` is the list of LangGraph nodes that
        executed THIS run (not historical state on the thread); use it to
        gate emission so a brief generated on turn 1 isn't re-emitted on
        every subsequent turn that happens to inherit the state.

        Return shape:
            {
                "brief": {...WeeklyBrief.model_dump()...},
                "package": {...PublisherPackage.model_dump()...},
            }
        """
        return {}

    async def run(self, input_data: dict, thread_id: str, stream: bool = False):
        app = await self.compile()
        config = {"configurable": {"thread_id": thread_id}}
        if stream:
            return app.astream_events(input_data, config=config, version="v2")
        return await app.ainvoke(input_data, config=config)

    async def resume(self, thread_id: str, approved: bool, payload: dict | None = None):
        """Resume a paused graph after human approval."""
        app = await self.compile()
        config = {"configurable": {"thread_id": thread_id}}
        if not approved:
            await app.aupdate_state(
                config,
                {"approval_result": "rejected", "approval_payload": payload},
            )
        return await app.ainvoke(None, config=config)

    async def get_state(self, thread_id: str):
        app = await self.compile()
        config = {"configurable": {"thread_id": thread_id}}
        return await app.aget_state(config)
