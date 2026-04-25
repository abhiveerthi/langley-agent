"""
Approvals runtime — pause detection, approve/reject resume, double-decision
guard.

Uses a MockApprovalAgent registered into AGENT_REGISTRY at import time so the
orchestrator's `get_agent()` lookup finds it. The mock has the same shape as
Brand Manager (interrupt_before=["approval_gate"], a draft → gate → execute
or revise → loop pattern) — just no LLM calls.
"""
from __future__ import annotations

import json
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from packages.agents.core.base import BaseAgent
from packages.agents.registry import AGENT_REGISTRY


# ── Mock agent that exercises the approvals runtime ───────────────────────
class _MockState(TypedDict):
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
    description = "Tiny agent for the approvals runtime tests."

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
        g = StateGraph(_MockState)
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

    async def _gate(self, _state):
        return {}

    async def _execute(self, _state):
        return {"sent": True}

    async def _revise(self, state):
        n = (state.get("revised_count") or 0) + 1
        return {
            "draft": f"DRAFT v{n + 1} (revised; feedback: {state.get('feedback') or '?'})",
            "revised_count": n,
            "approval_status": None,
            "feedback": None,
        }

    async def _respond(self, state):
        msg = "Sent!" if state.get("sent") else "Done."
        return {"messages": [AIMessage(content=msg)]}


# Register at import time. Survives across the test session — that's fine,
# nothing in production looks up "mock-approval-agent".
AGENT_REGISTRY[MockApprovalAgent.slug] = MockApprovalAgent


# Imports must come AFTER registry mutation so the orchestrator picks it up.
from app.services.approval_store import get_approval_store  # noqa: E402
from app.services.graph_orchestrator import (  # noqa: E402
    stream_new_run,
    stream_resume_approved,
    stream_resume_rejected,
)


# ── Helpers ───────────────────────────────────────────────────────────────
def _parse_event(sse: str) -> dict:
    return json.loads(sse.strip().removeprefix("data: "))


async def _collect(gen) -> list[dict]:
    return [_parse_event(chunk) async for chunk in gen]


# ── Tests ─────────────────────────────────────────────────────────────────
class TestApprovalsRuntime:
    """End-to-end exercise of the pause-detect → approve/reject → resume loop."""

    async def test_fresh_run_pauses_at_approval_gate(self):
        events = await _collect(stream_new_run(
            agent_slug=MockApprovalAgent.slug,
            message="send a thing",
            thread_id="t-pause",
            org_id="dev",
            user_id="dev",
        ))

        waiting = next((e for e in events if e["type"] == "waiting_approval"), None)
        assert waiting, "Expected waiting_approval event when graph hits interrupt_before"
        assert waiting["data"]["action_type"] == "mock_action"
        assert "DRAFT v1" in waiting["data"]["payload"]["draft"]
        # No `done` event means the graph paused, not completed.
        assert not any(e["type"] == "done" for e in events)

    async def test_reject_with_feedback_revises_and_repauses(self):
        events = await _collect(stream_new_run(
            agent_slug=MockApprovalAgent.slug,
            message="send a thing",
            thread_id="t-reject",
            org_id="dev",
            user_id="dev",
        ))
        approval_id = next(e for e in events if e["type"] == "waiting_approval")["data"]["approval_id"]

        events2 = await _collect(stream_resume_rejected(
            approval_id=approval_id,
            reviewer_user_id="tester",
            feedback="punchier",
        ))

        # First event: the audit record.
        assert events2[0]["type"] == "approval_recorded"
        assert events2[0]["data"]["decision"] == "rejected"

        # Revise loop ran → graph paused at the NEXT approval gate, with a
        # FRESH approval row (different id, evolved draft).
        new_waiting = next(e for e in events2 if e["type"] == "waiting_approval")
        assert new_waiting["data"]["approval_id"] != approval_id
        assert "DRAFT v2" in new_waiting["data"]["payload"]["draft"]

    async def test_approve_completes_the_graph(self):
        events = await _collect(stream_new_run(
            agent_slug=MockApprovalAgent.slug,
            message="send a thing",
            thread_id="t-approve",
            org_id="dev",
            user_id="dev",
        ))
        approval_id = next(e for e in events if e["type"] == "waiting_approval")["data"]["approval_id"]

        events2 = await _collect(stream_resume_approved(
            approval_id=approval_id,
            reviewer_user_id="tester",
        ))

        assert events2[0]["type"] == "approval_recorded"
        assert events2[0]["data"]["decision"] == "approved"
        assert events2[-1]["type"] == "done"
        sent = next((e for e in events2 if e["type"] == "token"), None)
        assert sent and "Sent!" in sent["data"]["content"]

    async def test_double_decision_returns_clean_error(self):
        events = await _collect(stream_new_run(
            agent_slug=MockApprovalAgent.slug,
            message="send a thing",
            thread_id="t-double",
            org_id="dev",
            user_id="dev",
        ))
        approval_id = next(e for e in events if e["type"] == "waiting_approval")["data"]["approval_id"]

        # Approve once.
        await _collect(stream_resume_approved(
            approval_id=approval_id, reviewer_user_id="tester",
        ))
        # Try to reject the same row a second time.
        events2 = await _collect(stream_resume_rejected(
            approval_id=approval_id, reviewer_user_id="tester", feedback="too late",
        ))
        assert events2[0]["type"] == "error"
        assert "already" in events2[0]["data"]["message"].lower()

    async def test_pending_approvals_drained_after_full_loop(self):
        # Run a full reject-then-approve cycle, then assert nothing is pending
        # for our test org. (Sanity check that the runtime cleans up after itself.)
        events = await _collect(stream_new_run(
            agent_slug=MockApprovalAgent.slug,
            message="drain test",
            thread_id="t-drain",
            org_id="dev",
            user_id="dev",
        ))
        first_id = next(e for e in events if e["type"] == "waiting_approval")["data"]["approval_id"]

        events2 = await _collect(stream_resume_rejected(
            approval_id=first_id, reviewer_user_id="tester", feedback="again",
        ))
        second_id = next(e for e in events2 if e["type"] == "waiting_approval")["data"]["approval_id"]

        await _collect(stream_resume_approved(
            approval_id=second_id, reviewer_user_id="tester",
        ))

        store = get_approval_store()
        pending = await store.list_pending("dev")
        # We just walked one through-line; only OUR thread's approvals should
        # be cleared. Other tests in the session can leave pending rows.
        my_thread_pending = [r for r in pending if r["thread_id"] == "t-drain"]
        assert my_thread_pending == []
