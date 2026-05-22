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

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
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


def _ai_message_text(msg: AIMessage | AIMessageChunk) -> str:
    """Flatten Claude's content-block list (or a chunk's content) into a plain string."""
    content = msg.content
    if isinstance(content, list):
        # Claude streams content as a list of blocks; tool-use blocks have no
        # "text" key, so they get filtered out here and surface via the
        # dedicated tool_call_start/end SSE events instead.
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return content or ""


# Graph nodes whose entry is too internal / too fast to be worth surfacing
# as a "thinking…" indicator. Two categories live here:
#
#   1. No-op / housekeeping nodes (load_profile, approval_gate, respond)
#      that flash past in milliseconds and would just add noise to the chat.
#   2. Internal LLM nodes whose output is JSON for state (intent classifier,
#      JSON extractor, target picker). Streaming raw model output from these
#      would dump `{"intent": "draft_pitch"}` into the bubble — the same set
#      is reused below to gate `on_chat_model_stream` events so those
#      internal model calls stay invisible to the user.
#
# Visible nodes (research_target_brand, draft_pitch, generate_kit,
# compose_brief, draft_reply, the ReAct loop agents, etc.) are deliberately
# absent so they DO surface the thinking indicator and DO stream tokens.
_THINKING_NODE_SKIP = {
    # No-op / housekeeping
    "load_profile",
    "load_brand_profile",
    "load_peer_context",
    "approval_gate",
    "respond",
    # Internal LLM calls — emit JSON for state, not user-facing prose
    "classify_intent",
    "extract_email",       # Brand Manager — parses draft into To/Subject/Body
    "extract_structured",  # Publisher — parses kit into typed package fields
    "pick_target",         # Community Manager — picks which comment to reply to
    # LangGraph sentinel node names
    "__start__",
    "__end__",
}


async def _compile_agent(agent: BaseAgent):
    """Compile an agent's graph against the shared checkpointer."""
    return agent.graph.compile(
        checkpointer=get_checkpointer(),
        interrupt_before=agent.interrupt_before_nodes,
    )


def _graph_node_names(agent: BaseAgent) -> set[str]:
    """Return the set of node names registered on the agent's StateGraph.

    Used to filter `astream_events` `on_chain_start` events down to actual
    graph nodes — the v2 event stream also fires for the outer graph, for
    RunnableSequence wrappers, and for tool/model invocations, none of
    which should drive the chat's thinking indicator.
    """
    try:
        return set(agent.graph.nodes.keys())  # StateGraph.nodes is a dict
    except Exception:
        return set()


async def _ensure_thread_row(
    *,
    org_id: str,
    thread_id: str,
    agent_slug: str,
    user_id: str | None = None,
    first_message: str | None = None,
) -> None:
    """Idempotently upsert a `threads` row so the chat-history + approvals
    FKs are satisfied.

    Runs via `current_supabase` (set on the request-scoped ContextVar). If the
    context isn't set (e.g. in dev without Supabase), quietly no-ops — the FK
    won't blow up because there's no real DB behind the in-memory store.

    `metadata.agent_slug` is what `list_threads` filters on so the MiniChat
    sidebar can show only this agent's chats. `agent_id` is looked up
    best-effort from the agents table (seeded per org by migration 014); if
    the lookup fails we still write the row so the chat persists.

    `first_message` seeds the title when a thread is being created for the
    first time — a short snippet of the user's prompt so the sidebar shows
    something meaningful instead of "untitled".
    """
    supabase = current_supabase.get()
    if supabase is None or not org_id or org_id == "dev":
        return
    try:
        agent_id = None
        try:
            res = (
                supabase.table("agents")
                .select("id")
                .eq("org_id", org_id)
                .eq("slug", agent_slug)
                .limit(1)
                .execute()
            )
            if res.data:
                agent_id = res.data[0]["id"]
        except Exception:
            pass

        payload: dict = {
            "id": thread_id,
            "org_id": org_id,
            "status": "active",
            "metadata": {"agent_slug": agent_slug},
        }
        if user_id and user_id != "dev":
            payload["user_id"] = user_id
        if agent_id:
            payload["agent_id"] = agent_id
        if first_message:
            # Trim to a sidebar-friendly length; the DB column is `text` so
            # the cap is purely cosmetic.
            payload["title"] = first_message.strip().splitlines()[0][:80]

        supabase.table("threads").upsert(payload, on_conflict="id").execute()
    except Exception as e:
        # Non-fatal — if the upsert fails, store.create will raise its own FK
        # error and the real diagnostic bubbles up from there.
        print(f"[orchestrator] _ensure_thread_row failed: {e!r}", flush=True)


def _persist_message(
    thread_id: str,
    role: str,
    content: str,
    metadata: dict | None = None,
) -> None:
    """Append a row to `messages` so the thread can be re-loaded later.

    No-op when there's no Supabase client on the ContextVar (dev/test) or
    when `content` is empty — empty assistant turns happen if the graph
    pauses before emitting any tokens, and we'd rather skip them than save
    blank bubbles.
    """
    supabase = current_supabase.get()
    if supabase is None or not content:
        return
    try:
        supabase.table("messages").insert(
            {
                "thread_id": thread_id,
                "role": role,
                "content": content,
                "metadata": metadata or {},
            }
        ).execute()
    except Exception as e:
        print(f"[orchestrator] _persist_message failed: {e!r}", flush=True)


def _extract_token_content(event_str: str) -> str | None:
    """If `event_str` is an SSE `token` event, return its content delta.

    Used by `stream_new_run` / `_resume` to accumulate the assistant's text
    as it streams, so we can write the final message to the DB at the end
    of the turn without having to re-walk LangGraph state.
    """
    if not event_str.startswith("data: "):
        return None
    try:
        data = json.loads(event_str[6:].strip())
    except Exception:
        return None
    if data.get("type") != "token":
        return None
    return data.get("data", {}).get("content")


async def _stream_until_done_or_pause(
    app,
    input_data: dict | None,
    config: dict,
    agent: BaseAgent,
    org_id: str,
    thread_id: str,
) -> AsyncIterator[str]:
    """Shared body used by both fresh-run and resume.

    Drives the graph via `astream_events(version="v2")` so we get three
    things at once:

      - per-token streaming via `on_chat_model_stream` (Claude AIMessageChunks)
      - per-node "thinking…" events via `on_chain_start` for graph nodes
      - per-tool call start/end events via `on_tool_start` / `on_tool_end`

    Synthetic AIMessages (e.g. Brand Manager's `_respond_node` repackaging
    `send_result` as the final reply) don't go through `on_chat_model_stream`
    because no LLM was invoked — those are emitted as a final `token` from
    the node's `on_chain_end`, with a dedup against what was already
    streamed so the ReAct-loop branches (where `_respond_node` just echoes
    the last AIMessage) don't duplicate text.

    After the event stream drains, we inspect graph state via `aget_state`
    to decide between `done` and a pause + `waiting_approval` event.
    """
    visited_nodes: list[str] = []
    streamed_buffer: list[str] = []  # all token content emitted so far (for dedup)
    tool_run_meta: dict[str, str] = {}  # run_id -> tool name (for matching end events)
    graph_node_names = _graph_node_names(agent)

    async for ev in app.astream_events(input_data, config=config, version="v2"):
        et = ev.get("event")
        name = ev.get("name") or ""
        data = ev.get("data") or {}

        # ── LLM token stream ───────────────────────────────────────────
        if et == "on_chat_model_stream":
            # LangGraph stamps `langgraph_node` on the event metadata when a
            # model invocation happens inside a graph node. We use it to
            # filter out internal LLM calls (intent classification, JSON
            # extraction) — their output is state plumbing, not chat prose.
            metadata = ev.get("metadata") or {}
            origin_node = metadata.get("langgraph_node") or ""
            if origin_node in _THINKING_NODE_SKIP:
                continue
            chunk = data.get("chunk")
            if not isinstance(chunk, (AIMessage, AIMessageChunk)):
                continue
            text = _ai_message_text(chunk)
            if text:
                streamed_buffer.append(text)
                yield _sse("token", {"content": text})
            continue

        # ── Graph node entry → thinking indicator ──────────────────────
        if et == "on_chain_start" and name in graph_node_names:
            visited_nodes.append(name)
            if name not in _THINKING_NODE_SKIP:
                yield _sse("agent_thinking", {"node": name})
            continue

        # ── Graph node exit → catch synthetic (non-LLM) AIMessages ────
        if et == "on_chain_end" and name in graph_node_names:
            output = data.get("output")
            if isinstance(output, dict):
                for msg in output.get("messages", []) or []:
                    if not isinstance(msg, AIMessage):
                        continue
                    text = _ai_message_text(msg)
                    if not text:
                        continue
                    # Skip if this exact text already streamed via tokens —
                    # avoids the duplicate when a terminal node just echoes
                    # the previous LLM message.
                    if text in "".join(streamed_buffer):
                        continue
                    # Separate from any preceding streamed text with a soft
                    # break so the synthetic reply doesn't run into prior
                    # ReAct-loop tokens.
                    if streamed_buffer:
                        yield _sse("token", {"content": "\n\n"})
                        streamed_buffer.append("\n\n")
                    streamed_buffer.append(text)
                    yield _sse("token", {"content": text})
            continue

        # ── Tool invocation ────────────────────────────────────────────
        if et == "on_tool_start":
            run_id = str(ev.get("run_id") or "")
            tool_run_meta[run_id] = name
            yield _sse("tool_call_start", {
                "id": run_id or name,
                "tool": name,
                "input": data.get("input") or {},
                "status": "running",
            })
            continue

        if et == "on_tool_end":
            run_id = str(ev.get("run_id") or "")
            output = data.get("output")
            output_str = ""
            if output is not None:
                # ToolMessage instances carry content; everything else stringifies.
                output_str = str(getattr(output, "content", output))
            yield _sse("tool_call_end", {
                "id": run_id or name,
                "tool": tool_run_meta.get(run_id, name),
                "output": output_str[:500],
                "status": "success",
            })
            continue

    # After astream returns, inspect the graph state to see if we paused at
    # an interrupt. state.next is a tuple of node names the graph is waiting
    # to execute — non-empty means "paused here, waiting for a resume".
    snapshot = await app.aget_state(config)

    # Emit any per-run structured outputs (Strategist's WeeklyBrief is the
    # first; Publisher's package is on deck). Each agent declares what's
    # interesting via `get_structured_outputs(state, visited_nodes)` — see
    # packages/agents/core/base.py. visited_nodes gates emission so the
    # same brief doesn't re-render on every follow-up turn.
    for kind, data in agent.get_structured_outputs(snapshot.values, visited_nodes).items():
        yield _sse("structured_output", {"kind": kind, "data": data})
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

    # The approvals table FKs thread_id -> threads(id). `stream_new_run`
    # already upserts the row at the top of the turn, but a paused-state
    # resume path may hit this branch without going through `stream_new_run`
    # first (e.g. an approval started in an earlier process). Keep the
    # idempotent upsert here as a safety net.
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

    # Ensure the threads row exists *before* we persist the user message —
    # `messages.thread_id` FKs to `threads.id`. Also seeds the title from
    # the first user message when the thread doesn't yet exist (the upsert
    # path only overwrites the title key if `first_message` is provided, so
    # follow-up turns won't clobber it via the brief snippet trick — but
    # the underlying upsert *will* keep the existing title because PostgREST
    # merges only the keys we send).
    await _ensure_thread_row(
        org_id=org_id,
        thread_id=thread_id,
        agent_slug=agent.slug,
        user_id=user_id,
        first_message=message,
    )
    _persist_message(thread_id, "user", message)

    assistant_buf: list[str] = []
    try:
        async for event in _stream_until_done_or_pause(
            app, input_data, config, agent, org_id, thread_id
        ):
            token = _extract_token_content(event)
            if token:
                assistant_buf.append(token)
            yield event
    except Exception as e:
        yield _sse("error", {"message": str(e)})
    finally:
        # Persist whatever the assistant produced before the turn ended (or
        # paused for approval). Resume paths append their own message rows
        # via `_resume`, so the conversation reads chronologically when
        # reloaded — pre-pause prose, then the post-resume continuation.
        if assistant_buf:
            _persist_message(thread_id, "assistant", "".join(assistant_buf))


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
    assistant_buf: list[str] = []
    try:
        async for event in _stream_until_done_or_pause(
            app, None, config, agent, org_id, thread_id
        ):
            token = _extract_token_content(event)
            if token:
                assistant_buf.append(token)
            yield event
    except Exception as e:
        yield _sse("error", {"message": str(e)})
    finally:
        if assistant_buf:
            _persist_message(
                thread_id,
                "assistant",
                "".join(assistant_buf),
                metadata={"resumed_from_approval": approval_id},
            )


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
