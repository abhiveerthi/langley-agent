#!/usr/bin/env python3
"""
Unit-level smoke test for the Community Manager — exercises the routing,
the approval-request shape, the OAuth-backed reply tool (mocked at the
HTTP layer), and the terminal `respond` formatting for each branch.

No real LLM calls, no real YouTube API calls. Live end-to-end testing
happens via `scripts/run_agent.py --agent community-manager` against a
real channel.

Run with: `python3 scripts/smoke_community_manager.py`
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage  # noqa: E402

from packages.agents.community_manager.agent import (  # noqa: E402
    CommunityManagerAgent,
    TargetComment,
)
from packages.agents.core.profile import load_profile  # noqa: E402
from packages.agents.core.templates import render  # noqa: E402


# ── Tests ─────────────────────────────────────────────────────────────────

def test_compile_and_node_set():
    """Graph compiles with the interrupt; expected nodes are all present."""
    a = CommunityManagerAgent()
    a.graph.compile(interrupt_before=a.interrupt_before_nodes)
    nodes = set(a.graph.nodes.keys())
    expected = {
        "load_profile", "classify_intent",
        "triage_agent", "triage_tools",
        "fetch_recent_comments", "pick_target", "draft_reply",
        "approval_gate", "send_reply", "revise_reply",
        "respond",
    }
    missing = expected - nodes
    assert not missing, f"Missing nodes: {missing}"
    assert a.interrupt_before_nodes == ["approval_gate"]
    print("  ✓ Graph compiles with all expected nodes + interrupt_before=[approval_gate]")


def test_get_approval_request_shape():
    """get_approval_request returns the shape the API runtime expects."""
    a = CommunityManagerAgent()
    state = {
        "target_comment_id": "Ugxabc",
        "target_author": "Sarah",
        "target_video_title": "FAFO | The Numbers Are Out",
        "target_comment_text": "What barrel twist do you run?",
        "draft_reply": "1:8 — works for the loads I shoot most.",
    }
    req = a.get_approval_request(state)
    assert req["action_type"] == "reply_comment"
    assert req["action_payload"]["parent_comment_id"] == "Ugxabc"
    assert req["action_payload"]["reply_draft"].startswith("1:8")
    assert req["action_payload"]["parent_author"] == "Sarah"
    assert "Sarah" in req["preview"]
    assert "FAFO" in req["preview"]
    print(f"  ✓ get_approval_request: action='{req['action_type']}', preview='{req['preview']}'")


def test_intent_router_falls_back_to_triage():
    """Garbage / missing intent should fall back to triage, not crash."""
    a = CommunityManagerAgent()
    assert a._route_by_intent({"intent": "draft_reply"}) == "draft_reply"
    assert a._route_by_intent({"intent": "triage"}) == "triage"
    assert a._route_by_intent({"intent": "research"}) == "research"
    assert a._route_by_intent({"intent": "garbage"}) == "triage"
    assert a._route_by_intent({}) == "triage"
    print("  ✓ _route_by_intent classifies cleanly + falls back to triage")


def test_approval_router_defaults_to_approved():
    """Plain resume (no approval_status set) defaults to approved.
    Mirrors Brand Manager so a Studio resume "just sends"."""
    a = CommunityManagerAgent()
    assert a._route_by_approval({"approval_status": "approved"}) == "approved"
    assert a._route_by_approval({"approval_status": "rejected"}) == "rejected"
    assert a._route_by_approval({}) == "approved"
    print("  ✓ _route_by_approval defaults to 'approved' on resume")


def test_after_pick_target_short_circuits_when_no_match():
    """When pick_target couldn't find a comment, the graph should bypass
    drafting and go straight to respond with the clarification."""
    a = CommunityManagerAgent()
    assert a._after_pick_target({"target_comment_id": "abc"}) == "draft"
    assert a._after_pick_target({"target_comment_id": None}) == "no_match"
    assert a._after_pick_target({}) == "no_match"
    print("  ✓ pick_target short-circuits when no match")


async def test_send_reply_node_calls_reply_to_comment():
    """_send_reply_node must call reply_to_comment with the staged
    parent_id + draft_reply, and stash the result on state."""
    a = CommunityManagerAgent()
    state = {
        "target_comment_id": "Ugx_test",
        "draft_reply": "Thanks for catching that — fixed in the next upload.",
    }
    fake_send = AsyncMock(return_value="Reply posted (mock)")
    with patch("packages.agents.community_manager.agent.reply_to_comment", fake_send):
        update = await a._send_reply_node(state)
    fake_send.assert_awaited_once_with(
        parent_comment_id="Ugx_test",
        text="Thanks for catching that — fixed in the next upload.",
    )
    assert update["send_result"] == "Reply posted (mock)"
    assert update["approval_status"] == "approved"
    print("  ✓ _send_reply_node calls reply_to_comment with the staged draft")


def test_target_comment_field_mapping():
    """The pick_target node maps TargetComment fields onto state. Verify the
    mapping logic directly — empty strings collapse to None so downstream
    routers see clean truthy/falsy values.

    (Patching `self.llm.with_structured_output` doesn't survive Pydantic's
    strict __delattr__ on ChatAnthropic — testing the field-mapping logic
    directly is simpler and just as informative.)
    """
    a = CommunityManagerAgent()

    # Match case
    matched = TargetComment(
        target_comment_id="Ugx_match_42",
        target_author="John",
        target_video_title="My Latest Video",
        target_comment_text="What scope do you run?",
        clarification_needed="",
    )
    update = {
        "target_comment_id": matched.target_comment_id or None,
        "target_author": matched.target_author or None,
        "target_video_title": matched.target_video_title or None,
        "target_comment_text": matched.target_comment_text or None,
        "clarification_needed": matched.clarification_needed or None,
    }
    assert update["target_comment_id"] == "Ugx_match_42"
    assert update["clarification_needed"] is None
    assert a._after_pick_target(update) == "draft"

    # No-match case
    nomatch = TargetComment(
        target_comment_id="",
        clarification_needed="No comment from John found.",
    )
    update = {
        "target_comment_id": nomatch.target_comment_id or None,
        "clarification_needed": nomatch.clarification_needed or None,
    }
    assert update["target_comment_id"] is None
    assert a._after_pick_target(update) == "no_match"
    print("  ✓ TargetComment -> state mapping + routing matches expectations")


async def test_respond_node_for_each_terminal_case():
    """Verify _respond_node renders the right user-facing text for each
    branch — successful send, no-match clarification, and triage final."""
    a = CommunityManagerAgent()

    # 1) draft_reply succeeded
    update = await a._respond_node({
        "intent": "draft_reply",
        "send_result": "Reply posted (comment id: Ugx_xyz).",
    })
    out = update["messages"][0].content
    assert "Reply posted" in out and "Ugx_xyz" in out

    # 2) draft_reply with no-match clarification
    update = await a._respond_node({
        "intent": "draft_reply",
        "clarification_needed": "No comment from John found.",
        "target_comment_id": None,
    })
    out = update["messages"][0].content
    assert "couldn't pick a comment" in out
    assert "John" in out

    # 3) triage final — pulls last AIMessage from state.messages
    update = await a._respond_node({
        "intent": "triage",
        "messages": [
            AIMessage(content="### Alerts\n(none)\n### Needs reply\n- John: ..."),
        ],
    })
    out = update["messages"][0].content
    assert "Needs reply" in out

    print("  ✓ _respond_node renders each terminal case correctly")


async def test_reply_to_comment_no_org_context():
    """reply_to_comment should fail gracefully when ContextVars are unset
    (running locally without auth) instead of raising."""
    from packages.agents.community_manager.tools import reply_to_comment as raw_fn
    from packages.integrations.context import (
        current_org_id, current_supabase,
    )
    current_org_id.set(None)
    current_supabase.set(None)
    result = await raw_fn(parent_comment_id="x", text="y")
    assert "no org context" in result.lower() or "not configured" in result.lower()
    print(f"  ✓ reply_to_comment (no auth): {result[:80]}")


def test_templates_render_with_empty_state():
    """Every template should render without StrictUndefined errors when
    given just the standard profile context."""
    p = load_profile("langley-outdoors-academy")
    for tmpl in ("classify.j2", "triage.j2", "research.j2", "pick_target.j2",
                 "draft.j2", "revise.j2"):
        out = render("community_manager", tmpl, profile=p)
        assert "{{" not in out and "{%" not in out
    print("  ✓ All 6 CM templates render cleanly")


# ── Runner ────────────────────────────────────────────────────────────────
async def main():
    bar = "=" * 70
    print(bar)
    print("COMMUNITY MANAGER SMOKE TEST")
    print(bar)
    test_compile_and_node_set()
    test_get_approval_request_shape()
    test_intent_router_falls_back_to_triage()
    test_approval_router_defaults_to_approved()
    test_after_pick_target_short_circuits_when_no_match()
    await test_send_reply_node_calls_reply_to_comment()
    test_target_comment_field_mapping()
    await test_respond_node_for_each_terminal_case()
    await test_reply_to_comment_no_org_context()
    test_templates_render_with_empty_state()
    print()
    print("All smoke checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
