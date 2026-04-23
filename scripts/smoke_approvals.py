#!/usr/bin/env python3
"""
Smoke test for the approvals runtime — verifies the orchestrator correctly:

  1. Detects graph pauses at `interrupt_before`
  2. Persists an approvals row with the agent's approval request payload
  3. Emits a `waiting_approval` SSE event on pause
  4. Resumes on approve (sets approval_status='approved' on state)
  5. Resumes on reject with feedback (sets approval_status='rejected' + feedback;
     Brand-Manager-style revise loop re-pauses at the next approval_gate)
  6. Rejects already-decided approvals with a clean error

Uses a tiny mock agent registered dynamically — NO real API calls, no LLM,
no external services. Run with: `python3 scripts/smoke_approvals.py`
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.graph.message import add_messages  # noqa: E402

from packages.agents.core.base import BaseAgent  # noqa: E402
from packages.agents.registry import AGENT_REGISTRY  # noqa: E402


# ── Mock agent with a simple approval gate + revise loop ──────────────────
class MockState(TypedDict):
    messages: Annotated[list, add_messages]
    org_id: str
    user_id: str
    thread_id: str
    task_id: str | None
    metadata: dict
    draft: str | None
    approval_status: str | None
    feedback: str | None
    sent: bool | None
    revised_count: int


class MockApprovalAgent(BaseAgent):
    slug = "mock-approval-agent"
    name = "Mock Approval Agent"
    description = "Tiny agent for testing the approvals runtime."

    @property
    def interrupt_before_nodes(self):
        return ["approval_gate"]

    def get_approval_request(self, state):
        return {
            "action_type": "mock_action",
            "action_payload": {"draft": state.get("draft")},
            "preview": f"Send: {(state.get('draft') or '')[:80]}",
        }

    def build_graph(self):
        g = StateGraph(MockState)
        g.add_node("draft", self._draft)
        g.add_node("approval_gate", self._gate)
        g.add_node("execute", self._execute)
        g.add_node("revise", self._revise)
        g.add_node("respond", self._respond)

        g.add_edge(START, "draft")
        g.add_edge("draft", "approval_gate")
        g.add_conditional_edges(
            "approval_gate",
            lambda s: "rejected" if (s.get("approval_status") or "approved") == "rejected" else "approved",
            {"approved": "execute", "rejected": "revise"},
        )
        g.add_edge("revise", "approval_gate")
        g.add_edge("execute", "respond")
        g.add_edge("respond", END)
        return g

    async def _draft(self, state):
        last = state["messages"][-1].content if state["messages"] else "?"
        return {"draft": f"DRAFT v1 for: {last}", "revised_count": 0}

    async def _gate(self, state):
        return {}  # interrupt fires before this node executes

    async def _execute(self, state):
        return {"sent": True}

    async def _revise(self, state):
        n = (state.get("revised_count") or 0) + 1
        return {
            "draft": f"DRAFT v{n + 1} (revised; feedback: {state.get('feedback') or '?'})",
            "revised_count": n,
            # Clear so the next gate starts fresh
            "approval_status": None,
            "feedback": None,
        }

    async def _respond(self, state):
        msg = "Sent!" if state.get("sent") else "Done."
        return {"messages": [AIMessage(content=msg)]}


# Register the mock before importing the orchestrator so `get_agent()` finds it.
AGENT_REGISTRY["mock-approval-agent"] = MockApprovalAgent


# Import after registration + after sys.path is extended with apps/api
from app.services.approval_store import get_approval_store  # noqa: E402
from app.services.graph_orchestrator import (  # noqa: E402
    stream_new_run,
    stream_resume_approved,
    stream_resume_rejected,
)


def parse_event(sse: str) -> dict:
    line = sse.strip().removeprefix("data: ")
    return json.loads(line)


async def collect(gen) -> list[dict]:
    return [parse_event(chunk) async for chunk in gen]


def _print_events(events: list[dict]) -> None:
    for e in events:
        print(f"  {e['type']}: {json.dumps(e['data'])[:120]}")


async def main() -> None:
    thread_id = "smoke-thread-1"
    bar = "=" * 70

    # STEP 1 — fresh run, pauses at approval_gate
    print(bar)
    print("STEP 1: fresh run — expect pause at approval_gate")
    print(bar)
    events = await collect(stream_new_run(
        agent_slug="mock-approval-agent",
        message="send a thing",
        thread_id=thread_id,
        org_id="dev",
        user_id="dev",
    ))
    _print_events(events)

    waiting = next((e for e in events if e["type"] == "waiting_approval"), None)
    assert waiting, "Expected waiting_approval event on pause"
    approval_id = waiting["data"]["approval_id"]
    assert "DRAFT v1" in waiting["data"]["payload"]["draft"], "Draft missing from payload"
    assert waiting["data"]["action_type"] == "mock_action"
    print(f"  ✓ Paused with approval_id={approval_id}")

    # STEP 2 — reject with feedback, graph revises and re-pauses
    print()
    print(bar)
    print("STEP 2: reject with feedback — expect revise + re-pause")
    print(bar)
    events2 = await collect(stream_resume_rejected(
        approval_id=approval_id,
        reviewer_user_id="tester",
        feedback="make it punchier",
    ))
    _print_events(events2)

    assert events2[0]["type"] == "approval_recorded"
    assert events2[0]["data"]["decision"] == "rejected"
    new_waiting = next((e for e in events2 if e["type"] == "waiting_approval"), None)
    assert new_waiting, "Expected new waiting_approval after revise loop"
    new_approval_id = new_waiting["data"]["approval_id"]
    assert new_approval_id != approval_id, "Expected a FRESH approval row for the next gate"
    assert "DRAFT v2" in new_waiting["data"]["payload"]["draft"], "Draft wasn't revised"
    print(f"  ✓ Revise loop ran, new approval_id={new_approval_id}")

    # STEP 3 — approve, graph completes
    print()
    print(bar)
    print("STEP 3: approve — expect execute + done")
    print(bar)
    events3 = await collect(stream_resume_approved(
        approval_id=new_approval_id,
        reviewer_user_id="tester",
    ))
    _print_events(events3)

    assert events3[0]["type"] == "approval_recorded"
    assert events3[0]["data"]["decision"] == "approved"
    assert events3[-1]["type"] == "done", "Expected terminal done event"
    sent_msg = next((e for e in events3 if e["type"] == "token"), None)
    assert sent_msg and "Sent!" in sent_msg["data"]["content"]
    print("  ✓ Graph completed through execute + respond")

    # STEP 4 — reject already-approved row, expect error
    print()
    print(bar)
    print("STEP 4: reject an already-approved approval — expect error")
    print(bar)
    events4 = await collect(stream_resume_rejected(
        approval_id=new_approval_id,
        reviewer_user_id="tester",
        feedback="changed my mind",
    ))
    _print_events(events4)
    assert events4[0]["type"] == "error"
    print("  ✓ Double-decision rejected cleanly")

    # STEP 5 — store state check
    print()
    print(bar)
    print("STEP 5: approval store state")
    print(bar)
    store = get_approval_store()
    pending = await store.list_pending("dev")
    print(f"  Pending approvals: {len(pending)} (expected 0)")
    assert len(pending) == 0

    print()
    print("All smoke checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
