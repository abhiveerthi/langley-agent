#!/usr/bin/env python3
"""
Smoke test for cross-agent shared context — verifies the loader, the
BaseAgent hydration node, the Strategist's persist path, and that prompt
templates correctly weave peer_context into rendered output.

No real API calls, no LLM, no Supabase — uses a `MockSupabase` whose
`.table(name).select(...).eq(...)…execute()` chain returns canned rows.
This catches everything except actual Postgres syntax / RLS issues, which
is exactly the right scope for a unit-style smoke test.

Run with: `python3 scripts/smoke_peer_context.py`
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.agents.core.peer_context import (  # noqa: E402
    PeerContext,
    load_peer_context,
    _is_real_uuid,
)
from packages.agents.core.templates import render  # noqa: E402
from packages.integrations.context import current_supabase  # noqa: E402


# ── MockSupabase: just enough surface to mimic the real chained client ────
class _MockResult:
    def __init__(self, data):
        self.data = data


class _MockQuery:
    def __init__(self, table_name: str, canned: dict):
        self._table = table_name
        self._canned = canned

    # The chained methods all return self so the call site can keep chaining.
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def insert(self, payload): self._canned.setdefault("_inserts", []).append((self._table, payload)); return self

    def execute(self):
        rows = self._canned.get(self._table, [])
        return _MockResult(rows)


class MockSupabase:
    """Mock Supabase client that returns canned rows per table.

    canned: { "table_name": [row_dict, ...] }. Append-only `_inserts`
    captures any insert calls so tests can assert on them.
    """

    def __init__(self, canned: dict):
        self._canned = canned

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._canned)


# ── Helpers ───────────────────────────────────────────────────────────────
def _real_uuid() -> str:
    return str(uuid.uuid4())


def _example_brief_row(headline: str = "Lean into the 2A education lane this week") -> dict:
    return {
        "headline": headline,
        "ideas": [
            {"title": "The 2A Argument Leftists Can't Refute", "confidence": "high"},
            {"title": "Every Gun Owner's 2026 Checklist", "confidence": "high"},
            {"title": "What VA's Block Means For 2026 Gun Laws", "confidence": "medium"},
        ],
        "created_at": "2026-04-25T12:00:00Z",
    }


def _example_package_row(title: str = "VA Redistricting BLOCKED") -> dict:
    return {
        "video_id": "abc123",
        "video_title": title,
        "status": "pushed",
        "description": "Hot take on the VA redistricting block.",
        "youtube_pushed_at": "2026-04-23T21:00:00Z",
        "created_at": "2026-04-23T20:00:00Z",
        "updated_at": "2026-04-23T21:00:00Z",
    }


# ── Tests ─────────────────────────────────────────────────────────────────
async def test_loader_dev_mode_empty():
    """Without Supabase or with a non-UUID org_id, return empty PeerContext."""
    pc = await load_peer_context(None, None)
    assert isinstance(pc, PeerContext)
    assert not pc.has_any()

    pc = await load_peer_context("dev", None)
    assert not pc.has_any()

    # Even with Supabase configured, "dev" org_id should skip the query.
    pc = await load_peer_context("dev", MockSupabase({}))
    assert not pc.has_any()
    print("  ✓ Dev-mode + non-UUID org_id returns empty PeerContext")


async def test_loader_with_real_org_and_brief():
    """Real UUID + Supabase with a brief row -> latest_brief populated."""
    org = _real_uuid()
    brief = _example_brief_row()
    sb = MockSupabase({"strategist_briefs": [brief]})
    pc = await load_peer_context(org, sb)
    assert pc.latest_brief is not None
    assert pc.latest_brief.headline == brief["headline"]
    assert len(pc.latest_brief.ideas) == 3
    assert pc.latest_package is None
    print("  ✓ Real org + brief row -> latest_brief populated, package None")


async def test_loader_handles_missing_publisher_table():
    """publisher_packages may not exist yet (lives on partner's branch).
    The loader should not raise."""
    org = _real_uuid()

    class ExplodingPackageQuery(_MockQuery):
        def execute(self):
            if self._table == "publisher_packages":
                raise Exception("relation 'publisher_packages' does not exist")
            return super().execute()

    class FaultySupabase(MockSupabase):
        def table(self, name):
            return ExplodingPackageQuery(name, self._canned)

    sb = FaultySupabase({"strategist_briefs": [_example_brief_row()]})
    pc = await load_peer_context(org, sb)
    assert pc.latest_brief is not None  # still got the brief
    assert pc.latest_package is None  # graceful failure on missing table
    print("  ✓ Missing publisher_packages table doesn't crash the loader")


async def test_loader_with_both_artifacts():
    """When both tables have rows, both fields populate."""
    org = _real_uuid()
    sb = MockSupabase({
        "strategist_briefs": [_example_brief_row()],
        "publisher_packages": [_example_package_row()],
    })
    pc = await load_peer_context(org, sb)
    assert pc.latest_brief is not None
    assert pc.latest_package is not None
    assert pc.latest_package.video_title == "VA Redistricting BLOCKED"
    assert pc.has_any()
    print("  ✓ Both brief + package populate cleanly")


async def test_baseagent_hydration_node_populates_state():
    """BaseAgent._load_peer_context_node merges PeerContext into state.metadata."""
    from packages.agents.core.base import BaseAgent

    class _StubAgent(BaseAgent):
        slug = "stub"

        def build_graph(self):  # required override
            from langgraph.graph import StateGraph, END, START

            class _S(BaseAgent.__dict__["_load_peer_context_node"].__annotations__.get("state", dict)):  # type: ignore
                pass
            g = StateGraph(dict)
            g.add_node("a", lambda s: {})
            g.add_edge(START, "a")
            g.add_edge("a", END)
            return g

    agent = _StubAgent()
    org = _real_uuid()
    sb = MockSupabase({"strategist_briefs": [_example_brief_row()]})
    current_supabase.set(sb)

    state = {"org_id": org, "metadata": {"existing_field": "kept"}}
    update = await agent._load_peer_context_node(state)

    assert "peer_context" in update["metadata"]
    assert update["metadata"]["existing_field"] == "kept"  # didn't clobber existing meta
    assert update["metadata"]["peer_context"]["latest_brief"]["headline"] == \
        _example_brief_row()["headline"]
    print("  ✓ BaseAgent._load_peer_context_node merges into state.metadata")


async def test_strategist_persist_brief_writes_to_supabase():
    """Strategist._persist_brief_node inserts into strategist_briefs when conditions met."""
    from packages.agents.strategist.agent import StrategistAgent

    agent = StrategistAgent()
    org = _real_uuid()
    thread = _real_uuid()

    canned = {}
    sb = MockSupabase(canned)
    current_supabase.set(sb)

    state = {
        "org_id": org,
        "thread_id": thread,
        "brief": {
            "headline": "Test headline",
            "ideas": [{"title": "I1", "hook": "H", "why_now": "W",
                       "confidence": "high", "rationale": "R", "citations": []}],
        },
    }
    await agent._persist_brief_node(state)
    assert "_inserts" in canned, "Expected an insert to be captured"
    inserts = canned["_inserts"]
    assert len(inserts) == 1
    table, payload = inserts[0]
    assert table == "strategist_briefs"
    assert payload["org_id"] == org
    assert payload["thread_id"] == thread
    assert payload["headline"] == "Test headline"
    assert len(payload["ideas"]) == 1
    print("  ✓ Strategist persist_brief writes a row when org_id is real")


async def test_strategist_persist_noop_in_dev():
    """No supabase configured -> persist is a no-op, no exception."""
    from packages.agents.strategist.agent import StrategistAgent

    agent = StrategistAgent()
    current_supabase.set(None)
    state = {
        "org_id": "dev",
        "brief": {"headline": "x", "ideas": []},
    }
    # Just verify it doesn't raise.
    await agent._persist_brief_node(state)
    print("  ✓ Strategist persist_brief is a clean no-op in dev mode")


def test_template_renders_peer_context():
    """draft.j2 renders the latest_brief headline when peer_context is present."""
    from packages.agents.core.profile import load_profile

    profile = load_profile("langley-outdoors-academy")
    peer = {
        "latest_brief": {
            "headline": "PEER_TEST_HEADLINE",
            "ideas": [
                {"title": "ideatitle1"}, {"title": "ideatitle2"}, {"title": "ideatitle3"},
            ],
        },
        "latest_package": None,
    }
    out = render("brand_manager", "draft.j2", profile=profile, peer_context=peer)
    assert "PEER_TEST_HEADLINE" in out, "Headline should be rendered into draft.j2"
    assert "ideatitle1" in out, "Idea title should be rendered"
    print("  ✓ Brand Manager draft.j2 renders peer_context.latest_brief")


def test_template_renders_strategist_continuity():
    """Strategist system.j2 + compose_brief.j2 render last-brief continuity block."""
    from packages.agents.core.profile import load_profile

    profile = load_profile("langley-outdoors-academy")
    peer = {
        "latest_brief": {
            "headline": "STRAT_CONTINUITY_TEST",
            "ideas": [{"title": "old1", "confidence": "high"}, {"title": "old2", "confidence": "medium"}],
        },
    }
    sys_out = render("strategist", "system.j2", profile=profile, intent="weekly_brief", peer_context=peer)
    assert "STRAT_CONTINUITY_TEST" in sys_out
    assert "old1" in sys_out
    assert "old2" in sys_out

    comp_out = render("strategist", "compose_brief.j2", profile=profile, peer_context=peer)
    assert "STRAT_CONTINUITY_TEST" in comp_out
    print("  ✓ Strategist templates render last-brief continuity block")


def test_template_omits_peer_context_when_absent():
    """Templates with no peer_context render cleanly — no jinja errors, no
    artifacts from the unused {% if %} block."""
    from packages.agents.core.profile import load_profile

    profile = load_profile("langley-outdoors-academy")

    # peer_context = empty dict (the dev-mode shape).
    out = render("brand_manager", "draft.j2", profile=profile, peer_context={})
    # The "Strategy Context" header only renders inside the if block.
    assert "Strategy Context" not in out
    # peer_context omitted entirely.
    out2 = render("brand_manager", "draft.j2", profile=profile)
    assert "Strategy Context" not in out2
    print("  ✓ Templates omit peer_context block cleanly when absent")


# ── Runner ────────────────────────────────────────────────────────────────
async def main():
    bar = "=" * 70
    print(bar)
    print("CROSS-AGENT CONTEXT SMOKE TEST")
    print(bar)
    assert _is_real_uuid(_real_uuid())
    assert not _is_real_uuid("dev")
    assert not _is_real_uuid(None)
    assert not _is_real_uuid("")
    print("  ✓ _is_real_uuid behaves on edge cases")
    await test_loader_dev_mode_empty()
    await test_loader_with_real_org_and_brief()
    await test_loader_handles_missing_publisher_table()
    await test_loader_with_both_artifacts()
    await test_baseagent_hydration_node_populates_state()
    await test_strategist_persist_brief_writes_to_supabase()
    await test_strategist_persist_noop_in_dev()
    test_template_renders_peer_context()
    test_template_renders_strategist_continuity()
    test_template_omits_peer_context_when_absent()
    print()
    print("All smoke checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
