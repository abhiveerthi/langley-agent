"""
LangGraph runtime with human-in-the-loop approval glue.

This module is the single place where the API converts a LangGraph execution
into an SSE event stream the frontend can consume, and the single place where
paused graphs get resumed after an approve/reject decision.

Three entry points, each yielding SSE-formatted strings:

  - `stream_new_run`      — fresh user message, runs the graph from scratch
  - `stream_resume_approved` — resumes a paused graph with approval_status set
  - `stream_resume_rejected` — resumes with rejection + optional feedback
                               (Brand Manager uses feedback to revise_pitch
                               and then pause at approval_gate again)

Pause detection works by checking `state.next` after astream() finishes.
LangGraph populates it with the tuple of nodes the graph is currently waiting
at when an interrupt fires. If it's non-empty, the graph is paused; we pull
the agent's approval-request shape off the state, persist an approvals row,
and emit a `waiting_approval` SSE event carrying the approval_id + payload.

## Checkpointer lifecycle

- **Production** (FastAPI lifespan calls `init_checkpointer()` at startup):
  AsyncPostgresSaver bound to `DATABASE_URL`. Paused state survives API
  restarts because LangGraph's checkpoint tables are persistent.
- **Dev** (no `DATABASE_URL`, or Postgres unreachable, or no lifespan):
  MemorySaver fallback. Paused state survives across requests within one
  uvicorn worker, lost on restart. Acceptable for local iteration.

Tests don't go through the FastAPI lifespan, so they hit the lazy
`get_checkpointer()` path which returns MemorySaver — no test setup needed.
"""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from packages.agents.core.base import BaseAgent
from packages.agents.registry import get_agent
from packages.integrations.context import current_supabase

from app.services.approval_store import get_approval_store


# ── Shared checkpointer (lifespan-managed) ────────────────────────────────
# `_checkpointer` is the singleton used by every compile call. Started as
# None; populated by `init_checkpointer()` (FastAPI lifespan) or the lazy
# fallback in `get_checkpointer()` (test paths).
#
# `_checkpointer_cm` holds the AsyncPostgresSaver's async context manager so
# we can call __aexit__ on shutdown. None for the MemorySaver fallback.
_checkpointer: Any = None
_checkpointer_cm: Any = None


async def init_checkpointer() -> None:
    """Initialise the shared checkpointer for the API's lifetime.

    Called from FastAPI's lifespan handler. Idempotent. Picks
    AsyncPostgresSaver when `DATABASE_URL` is set and Postgres is reachable,
    falls back to MemorySaver otherwise so `pnpm dev` doesn't require a
    running database.
    """
    global _checkpointer, _checkpointer_cm
    if _checkpointer is not None:
        return  # already initialised

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        _checkpointer = MemorySaver()
        print("[checkpointer] DATABASE_URL not set; using MemorySaver", flush=True)
        return

    try:
        # `from_conn_string` is an async context manager that yields a
        # bound AsyncPostgresSaver. We `__aenter__` manually so the
        # returned saver lives for the app's lifetime; `close_checkpointer`
        # runs the matching `__aexit__` on shutdown.
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        _checkpointer_cm = AsyncPostgresSaver.from_conn_string(db_url)
        _checkpointer = await _checkpointer_cm.__aenter__()
        # `setup()` runs CREATE TABLE IF NOT EXISTS for LangGraph's internal
        # checkpoint tables (`checkpoints`, `checkpoint_blobs`,
        # `checkpoint_writes`). Idempotent.
        await _checkpointer.setup()
        print("[checkpointer] AsyncPostgresSaver bound to DATABASE_URL", flush=True)
    except Exception as e:
        # Production should fail loud here — silent fallback would mean
        # paused approvals quietly stop surviving restarts.
        env = os.environ.get("ENVIRONMENT", "").lower()
        if env == "production":
            raise

        print(
            f"[checkpointer] AsyncPostgresSaver unavailable ({e}); "
            "falling back to MemorySaver",
            flush=True,
        )
        _checkpointer_cm = None
        _checkpointer = MemorySaver()


async def close_checkpointer() -> None:
    """Cleanly close the AsyncPostgresSaver's connection on shutdown.

    Called from FastAPI's lifespan handler. No-op for MemorySaver paths.
    """
    global _checkpointer, _checkpointer_cm
    if _checkpointer_cm is not None:
        try:
            await _checkpointer_cm.__aexit__(None, None, None)
        except Exception as e:
            print(f"[checkpointer] close failed: {e!r}", flush=True)
    _checkpointer_cm = None
    _checkpointer = None


def get_checkpointer():
    """Return the shared checkpointer.

    Lazy-initialises a MemorySaver if `init_checkpointer()` hasn't run
    (test paths, ad-hoc scripts). Production paths always go through the
    FastAPI lifespan which sets up AsyncPostgresSaver before any request
    can call this.
    """
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = MemorySaver()
    return _checkpointer


def _sse(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event envelope."""
    return f"data: {json.dumps({'type': event_type, 'data': data})}\n\n"


def _ai_message_text(msg: AIMessage) -> str:
    """Flatten Claude's content-block list into a plain string."""
    content = msg.content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return content or ""


def _emit_message_events(messages: list) -> list[str]:
    """Translate LangGraph message deltas into SSE events."""
    events: list[str] = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            text = _ai_message_text(msg)
            if text:
                events.append(_sse("token", {"content": text}))
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    events.append(_sse("tool_call_start", {
                        "id": tc.get("id", ""),
                        "tool": tc.get("name", ""),
                        "input": tc.get("args", {}),
                        "status": "running",
                    }))
        elif isinstance(msg, ToolMessage):
            events.append(_sse("tool_call_end", {
                "id": msg.tool_call_id,
                "tool": msg.name,
                "output": str(msg.content)[:500],
                "status": "success",
            }))
    return events


async def _compile_agent(agent: BaseAgent):
    """Compile an agent's graph against the shared checkpointer."""
    return agent.graph.compile(
        checkpointer=get_checkpointer(),
        interrupt_before=agent.interrupt_before_nodes,
    )


async def _ensure_thread_row(*, org_id: str, thread_id: str, agent_slug: str) -> None:
    """Idempotently upsert a `threads` row so the approvals FK is satisfied.

    Runs via `current_supabase` (set on the request-scoped ContextVar). If the
    context isn't set (e.g. in dev without Supabase), quietly no-ops — the FK
    won't blow up because there's no real DB behind the in-memory store.
    """
    supabase = current_supabase.get()
    if supabase is None or not org_id or org_id == "dev":
        return
    try:
        supabase.table("threads").upsert(
            {
                "id": thread_id,
                "org_id": org_id,
                "title": f"{agent_slug} approval gate",
                "status": "active",
            },
            on_conflict="id",
        ).execute()
    except Exception as e:
        # Non-fatal — if the upsert fails, store.create will raise its own FK
        # error and the real diagnostic bubbles up from there.
        print(f"[orchestrator] _ensure_thread_row failed: {e!r}", flush=True)


async def _stream_until_done_or_pause(
    app,
    input_data: dict | None,
    config: dict,
    agent: BaseAgent,
    org_id: str,
    thread_id: str,
) -> AsyncIterator[str]:
    """Shared body used by both fresh-run and resume.

    Runs `app.astream` to completion or until LangGraph pauses at an interrupt,
    emits per-node SSE events, and (if paused) inserts an approvals row + emits
    a `waiting_approval` event with the approval payload. Yields `done` at the
    end if the graph completed without pausing.
    """
    visited_nodes: list[str] = []
    async for chunk in app.astream(input_data, config=config, stream_mode="updates"):
        for _node, node_data in chunk.items():
            visited_nodes.append(_node)
            if not node_data:
                continue
            for event in _emit_message_events(node_data.get("messages", [])):
                yield event

    # After astream returns, inspect the graph state to see if we paused at
    # an interrupt. state.next is a tuple of node names the graph is waiting
    # to execute — non-empty means "paused here, waiting for a resume".
    snapshot = await app.aget_state(config)
    print(
        f"[orchestrator] agent={agent.slug} thread={thread_id} "
        f"visited={visited_nodes} snapshot.next={snapshot.next} "
        f"interrupt_before={agent.interrupt_before_nodes}",
        flush=True,
    )
    if not snapshot.next:
        yield _sse("done", {})
        return

    # Paused. Ask the agent to describe what's being gated so we can persist
    # an approval row and tell the frontend what to render.
    approval_req = agent.get_approval_request(snapshot.values) or {
        "action_type": "unknown",
        "action_payload": {},
        "preview": "An agent action is waiting for your review.",
    }

    # The approvals table FKs thread_id -> threads(id). LangGraph manages its
    # own thread_id via the checkpointer, but nothing has inserted a matching
    # row in the legacy threads table — so insert one now (idempotent upsert).
    # Keeps the FK happy and gives us a future hook for linking LangGraph
    # threads to the chat-history table.
    await _ensure_thread_row(org_id=org_id, thread_id=thread_id, agent_slug=agent.slug)

    store = get_approval_store()
    try:
        row = await store.create(
            org_id=org_id,
            thread_id=thread_id,
            requested_by_agent=agent.slug,
            action_type=approval_req["action_type"],
            action_payload=approval_req["action_payload"],
            preview=approval_req["preview"],
        )
        print(f"[orchestrator] approval row created id={row.get('id')}", flush=True)
    except Exception as e:
        print(f"[orchestrator] approval store.create FAILED: {e!r}", flush=True)
        raise
    yield _sse("waiting_approval", {
        "approval_id": row["id"],
        "thread_id": thread_id,
        "agent_slug": agent.slug,
        "action_type": approval_req["action_type"],
        "preview": approval_req["preview"],
        "payload": approval_req["action_payload"],
    })


# ── Public entry points ───────────────────────────────────────────────────

async def stream_new_run(
    *,
    agent_slug: str,
    message: str,
    thread_id: str,
    org_id: str,
    user_id: str,
    extra_state: dict | None = None,
) -> AsyncIterator[str]:
    """Start a fresh agent run and stream events until done or pause.

    `extra_state` lets callers pre-populate fields on the agent's state dict
    (e.g. intent, video_id, package_id for one-click Publisher actions) so
    the agent can skip LLM-based intent parsing.
    """
    agent = get_agent(agent_slug)
    app = await _compile_agent(agent)

    input_data: dict = {
        "messages": [HumanMessage(content=message)],
        "org_id": org_id,
        "user_id": user_id,
        "thread_id": thread_id,
        "task_id": None,
        "metadata": {},
    }
    if extra_state:
        input_data.update(extra_state)
    config = {"configurable": {"thread_id": thread_id}}

    try:
        async for event in _stream_until_done_or_pause(
            app, input_data, config, agent, org_id, thread_id
        ):
            yield event
    except Exception as e:
        yield _sse("error", {"message": str(e)})


async def _resume(
    *,
    approval_id: str,
    reviewer_user_id: str,
    decision: str,                      # "approved" | "rejected"
    feedback: str | None = None,
) -> AsyncIterator[str]:
    """Shared resume body — flips the approval row, updates graph state,
    then continues execution streaming events until done or the next pause."""
    store = get_approval_store()
    row = await store.get(approval_id)
    if not row:
        yield _sse("error", {"message": f"Approval {approval_id} not found"})
        return
    if row["status"] != "pending":
        yield _sse("error", {
            "message": f"Approval already {row['status']}",
        })
        return

    agent_slug = row["requested_by_agent"]
    thread_id = row["thread_id"]
    org_id = row["org_id"]

    agent = get_agent(agent_slug)
    app = await _compile_agent(agent)
    config = {"configurable": {"thread_id": thread_id}}

    # Patch approval_status (and feedback, if rejecting) onto the paused state.
    # Brand Manager's _route_by_approval conditional reads these on resume to
    # pick send_email vs revise_pitch.
    state_patch: dict = {"approval_status": decision}
    if decision == "rejected":
        state_patch["feedback"] = feedback or ""
    await app.aupdate_state(config, state_patch)

    # Record the human decision on the approval row BEFORE resuming, so the
    # audit trail is in place even if the resumed graph crashes.
    await store.update_status(
        approval_id, status=decision, reviewed_by=reviewer_user_id
    )
    yield _sse("approval_recorded", {
        "approval_id": approval_id,
        "decision": decision,
    })

    # Resume by passing None as input — LangGraph picks up at the next node
    # after the interrupt. Graph may pause again (Brand Manager reject loop
    # revise_pitch -> approval_gate), and the pause handler creates a fresh
    # approval row for the next gate.
    try:
        async for event in _stream_until_done_or_pause(
            app, None, config, agent, org_id, thread_id
        ):
            yield event
    except Exception as e:
        yield _sse("error", {"message": str(e)})


async def stream_resume_approved(
    *, approval_id: str, reviewer_user_id: str,
) -> AsyncIterator[str]:
    async for ev in _resume(
        approval_id=approval_id,
        reviewer_user_id=reviewer_user_id,
        decision="approved",
    ):
        yield ev


async def stream_resume_rejected(
    *, approval_id: str, reviewer_user_id: str, feedback: str | None,
) -> AsyncIterator[str]:
    async for ev in _resume(
        approval_id=approval_id,
        reviewer_user_id=reviewer_user_id,
        decision="rejected",
        feedback=feedback,
    ):
        yield ev
