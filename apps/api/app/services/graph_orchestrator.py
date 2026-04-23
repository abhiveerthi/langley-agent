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

Checkpointer is a module-level MemorySaver singleton so paused state survives
across requests within one uvicorn worker. Production will upgrade to
AsyncPostgresSaver (tracked as part of backlog item B — tenancy).
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from packages.agents.core.base import BaseAgent
from packages.agents.registry import get_agent

from app.services.approval_store import get_approval_store


# ── Shared checkpointer ───────────────────────────────────────────────────
# Module-level so every request in the same process hits the same store.
# Dev-only; wire AsyncPostgresSaver in for production (backlog: B tenancy).
_checkpointer = MemorySaver()


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
    """Compile an agent's graph against the shared in-memory checkpointer."""
    return agent.graph.compile(
        checkpointer=_checkpointer,
        interrupt_before=agent.interrupt_before_nodes,
    )


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
    async for chunk in app.astream(input_data, config=config, stream_mode="updates"):
        for _node, node_data in chunk.items():
            if not node_data:
                continue
            for event in _emit_message_events(node_data.get("messages", [])):
                yield event

    # After astream returns, inspect the graph state to see if we paused at
    # an interrupt. state.next is a tuple of node names the graph is waiting
    # to execute — non-empty means "paused here, waiting for a resume".
    snapshot = await app.aget_state(config)
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
    store = get_approval_store()
    row = await store.create(
        org_id=org_id,
        thread_id=thread_id,
        requested_by_agent=agent.slug,
        action_type=approval_req["action_type"],
        action_payload=approval_req["action_payload"],
        preview=approval_req["preview"],
    )
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
) -> AsyncIterator[str]:
    """Start a fresh agent run and stream events until done or pause."""
    agent = get_agent(agent_slug)
    app = await _compile_agent(agent)

    input_data = {
        "messages": [HumanMessage(content=message)],
        "org_id": org_id,
        "user_id": user_id,
        "thread_id": thread_id,
        "task_id": None,
        "metadata": {},
    }
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
