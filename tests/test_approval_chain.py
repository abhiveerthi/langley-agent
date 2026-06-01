"""
Multi-step (sequential) approval-chain runtime tests.

Companion to test_approvals.py. Exercises the per-agent ORDERED approval chain
added in migration 019: an agent can declare `approval_chain(state) ->
list[str]` (or an `approval_policy.approvers` manifest block) so a gate requires
N approvals IN ORDER before the graph resumes and the write executes.

Invariants covered:
  (a) the default single-step agent behaves EXACTLY as before — one approve
      resumes immediately (regression guard, lives alongside the two-step case);
  (b) a two-step chain needs two approvals; the first approve advances to a
      FRESH pending row at step 1 WITHOUT resuming the graph (sent stays unset);
  (c) reject at step 0 does NOT advance — it runs the revise loop and re-pauses
      back at step 0 of a fresh chain;
  (d) cancel kills the chain (handled via the store; no further pending row).

Hermetic: reuses the in-memory store (org_id="dev" → no Supabase context), no
LLM, no DB.
"""
from __future__ import annotations

import json
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from packages.agents.core.base import BaseAgent
from packages.agents.registry import AGENT_REGISTRY


# ── Two-step chain mock agent ─────────────────────────────────────────────
# Same draft → gate → execute | revise → loop shape as MockApprovalAgent, but
# declares a TWO-step approval chain (["reviewer", "owner"]). Only the final
# (owner) approval should resume the graph and set `sent`.
class _ChainState(TypedDict):
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


class TwoStepApprovalAgent(BaseAgent):
    slug = "two-step-approval-agent"
    name = "Two Step Approval Agent"
    description = "Mock agent requiring reviewer-then-owner approval."

    @property
    def interrupt_before_nodes(self):
        return ["approval_gate"]

    def approval_chain(self, state):
        return ["reviewer", "owner"]

    def get_approval_request(self, state):
        return {
            "action_type": "mock_publish",
            "action_payload": {"draft": state.get("draft")},
            "preview": f"Publish: {(state.get('draft') or '')[:80]}",
        }

    def build_graph(self):
        g = StateGraph(_ChainState)
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
        msg = "Published!" if state.get("sent") else "Done."
        return {"messages": [AIMessage(content=msg)]}


AGENT_REGISTRY[TwoStepApprovalAgent.slug] = TwoStepApprovalAgent


# Imports AFTER registry mutation so the orchestrator's get_agent() sees it.
# `MockApprovalAgent` (single-step default) is registered by test_approvals.
from app.services.approval_store import get_approval_store  # noqa: E402
from app.services.graph_orchestrator import (  # noqa: E402
    stream_new_run,
    stream_resume_approved,
    stream_resume_rejected,
)


def _parse_event(sse: str) -> dict:
    return json.loads(sse.strip().removeprefix("data: "))


async def _collect(gen) -> list[dict]:
    return [_parse_event(chunk) async for chunk in gen]


def _waiting(events: list[dict]) -> dict | None:
    return next((e for e in events if e["type"] == "waiting_approval"), None)


class TestApprovalChain:
    # ── (a) default single-step regression ────────────────────────────────
    async def test_single_step_default_resumes_immediately(self):
        """An agent with no chain override = ["approver"] single step. One
        approve must resume to completion (today's behaviour, unchanged)."""
        events = await _collect(stream_new_run(
            agent_slug="mock-approval-agent",
            message="send a thing",
            thread_id="chain-single",
            org_id="dev",
            user_id="dev",
        ))
        waiting = _waiting(events)
        assert waiting, "single-step agent should still pause once"
        # Single-step still surfaces additive chain metadata, defaulting to one.
        assert waiting["data"]["total_steps"] == 1
        assert waiting["data"]["chain"] == ["approver"]
        assert waiting["data"]["remaining_approvers"] == []
        approval_id = waiting["data"]["approval_id"]

        events2 = await _collect(stream_resume_approved(
            approval_id=approval_id, reviewer_user_id="tester",
        ))
        # Resumes straight to completion — no second waiting_approval.
        assert events2[0]["data"]["resuming"] is True
        assert events2[0]["data"]["advanced"] is False
        assert events2[-1]["type"] == "done"
        assert _waiting(events2) is None

    # ── (b) two-step chain needs two approvals ────────────────────────────
    async def test_two_step_chain_requires_two_approvals(self):
        events = await _collect(stream_new_run(
            agent_slug=TwoStepApprovalAgent.slug,
            message="ship the post",
            thread_id="chain-two",
            org_id="dev",
            user_id="dev",
        ))
        w0 = _waiting(events)
        assert w0, "two-step agent must pause at step 0"
        d0 = w0["data"]
        assert d0["chain"] == ["reviewer", "owner"]
        assert d0["total_steps"] == 2
        assert d0["step_index"] == 0
        assert d0["approver_role"] == "reviewer"
        assert d0["remaining_approvers"] == ["owner"]
        first_id = d0["approval_id"]

        # First approve: advances to step 1, does NOT resume the graph.
        events2 = await _collect(stream_resume_approved(
            approval_id=first_id, reviewer_user_id="reviewer-user",
        ))
        rec = events2[0]
        assert rec["type"] == "approval_recorded"
        assert rec["data"]["decision"] == "approved"
        assert rec["data"]["advanced"] is True
        assert rec["data"]["approver_role"] == "reviewer"
        # A fresh pending row appeared for the OWNER step — different id.
        w1 = _waiting(events2)
        assert w1, "first approve must create a new pending row at step 1"
        d1 = w1["data"]
        assert d1["approval_id"] != first_id
        assert d1["step_index"] == 1
        assert d1["approver_role"] == "owner"
        assert d1["remaining_approvers"] == []
        # Graph did NOT resume — no done, write hasn't executed.
        assert not any(e["type"] == "done" for e in events2)
        second_id = d1["approval_id"]

        # Step-0 row is now approved; step-1 row is the only pending one.
        store = get_approval_store()
        pending = [r for r in await store.list_pending("dev")
                   if r["thread_id"] == "chain-two"]
        assert len(pending) == 1 and pending[0]["id"] == second_id

        # Second (final) approve: resumes and completes.
        events3 = await _collect(stream_resume_approved(
            approval_id=second_id, reviewer_user_id="owner-user",
        ))
        assert events3[0]["data"]["resuming"] is True
        assert events3[0]["data"]["advanced"] is False
        assert events3[-1]["type"] == "done"
        published = next((e for e in events3 if e["type"] == "token"), None)
        assert published and "Published!" in published["data"]["content"]
        # Chain fully drained.
        pending = [r for r in await store.list_pending("dev")
                   if r["thread_id"] == "chain-two"]
        assert pending == []

    # ── (c) reject at step 0 does not advance ─────────────────────────────
    async def test_reject_at_step_zero_does_not_advance(self):
        events = await _collect(stream_new_run(
            agent_slug=TwoStepApprovalAgent.slug,
            message="ship it",
            thread_id="chain-reject",
            org_id="dev",
            user_id="dev",
        ))
        first_id = _waiting(events)["data"]["approval_id"]

        events2 = await _collect(stream_resume_rejected(
            approval_id=first_id, reviewer_user_id="reviewer-user",
            feedback="punchier",
        ))
        assert events2[0]["data"]["decision"] == "rejected"
        # Reject runs the revise loop and re-pauses at a FRESH chain step 0
        # (reviewer again, not owner) — it must NOT have advanced to owner.
        w = _waiting(events2)
        assert w, "reject should revise and re-pause"
        assert w["data"]["approval_id"] != first_id
        assert w["data"]["step_index"] == 0
        assert w["data"]["approver_role"] == "reviewer"
        assert "DRAFT v2" in w["data"]["payload"]["draft"]
        assert not any(e["type"] == "done" for e in events2)

    # ── (d) cancel kills the chain ────────────────────────────────────────
    async def test_cancel_kills_the_chain(self):
        events = await _collect(stream_new_run(
            agent_slug=TwoStepApprovalAgent.slug,
            message="ship maybe",
            thread_id="chain-cancel",
            org_id="dev",
            user_id="dev",
        ))
        first_id = _waiting(events)["data"]["approval_id"]

        store = get_approval_store()
        # Cancel mirrors the router: flip status, do not resume.
        await store.update_status(first_id, status="cancelled", reviewed_by="tester")

        # No pending rows remain for this thread — the chain is dead. No
        # step-1 row was ever created, and re-approving the cancelled row is
        # rejected as already-resolved.
        pending = [r for r in await store.list_pending("dev")
                   if r["thread_id"] == "chain-cancel"]
        assert pending == []

        events2 = await _collect(stream_resume_approved(
            approval_id=first_id, reviewer_user_id="tester",
        ))
        assert events2[0]["type"] == "error"
        assert "already" in events2[0]["data"]["message"].lower()
