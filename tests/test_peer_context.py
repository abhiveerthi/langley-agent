"""
Cross-agent peer context — loader behaviour, BaseAgent hydration node,
Strategist persist path, template rendering of `peer_context.latest_brief`.
"""
from __future__ import annotations

import pytest

from packages.agents.core.peer_context import (
    PeerContext,
    _is_real_uuid,
    load_peer_context,
)
from packages.agents.core.templates import render
from packages.integrations.context import current_supabase


def _example_brief_row(headline: str = "Lean into the 2A education lane") -> dict:
    return {
        "headline": headline,
        "ideas": [
            {"title": "The 2A Argument Leftists Can't Refute", "confidence": "high"},
            {"title": "Every Gun Owner's 2026 Checklist", "confidence": "high"},
        ],
        "created_at": "2026-04-25T12:00:00Z",
    }


def _example_package_row(title: str = "VA Redistricting BLOCKED") -> dict:
    return {
        "video_id": "abc123",
        "video_title": title,
        "status": "pushed",
        "description": "Hot take.",
        "youtube_pushed_at": "2026-04-23T21:00:00Z",
        "created_at": "2026-04-23T20:00:00Z",
        "updated_at": "2026-04-23T21:00:00Z",
    }


# ── _is_real_uuid edge cases ──────────────────────────────────────────────
class TestIsRealUuid:
    @pytest.mark.parametrize("value, expected", [
        ("dev", False),
        ("", False),
        (None, False),
        ("not-a-uuid", False),
        ("123e4567-e89b-12d3-a456-426614174000", True),
    ])
    def test_classifies_correctly(self, value, expected):
        assert _is_real_uuid(value) is expected


# ── Loader degradation paths ──────────────────────────────────────────────
class TestLoadPeerContextDegradation:
    """Loader returns empty PeerContext (never raises) when conditions aren't
    met for a real Supabase read."""

    async def test_no_supabase(self):
        pc = await load_peer_context(None, None)
        assert isinstance(pc, PeerContext)
        assert not pc.has_any()

    async def test_dev_org_id(self):
        pc = await load_peer_context("dev", None)
        assert not pc.has_any()

    async def test_dev_org_id_with_configured_supabase(self, mock_supabase_factory):
        # Even if Supabase is plumbed, "dev" org_id should skip the query.
        pc = await load_peer_context("dev", mock_supabase_factory())
        assert not pc.has_any()


# ── Loader read paths ─────────────────────────────────────────────────────
class TestLoadPeerContextReads:
    async def test_real_org_with_brief_only(self, real_uuid, mock_supabase_factory):
        sb = mock_supabase_factory({"strategist_briefs": [_example_brief_row()]})
        pc = await load_peer_context(real_uuid, sb)
        assert pc.latest_brief is not None
        assert pc.latest_brief.headline == _example_brief_row()["headline"]
        assert len(pc.latest_brief.ideas) == 2
        assert pc.latest_package is None

    async def test_real_org_with_both_artifacts(self, real_uuid, mock_supabase_factory):
        sb = mock_supabase_factory({
            "strategist_briefs": [_example_brief_row()],
            "publisher_packages": [_example_package_row()],
        })
        pc = await load_peer_context(real_uuid, sb)
        assert pc.latest_brief is not None
        assert pc.latest_package is not None
        assert pc.latest_package.video_title == "VA Redistricting BLOCKED"
        assert pc.has_any()

    async def test_missing_publisher_table_does_not_raise(self, real_uuid, mock_supabase_factory):
        """publisher_packages may not exist on main yet — query optimistically,
        swallow the inevitable 'relation does not exist' error."""

        # Subclass the factory's class so we can override `table()` to raise.
        BaseClass = type(mock_supabase_factory())

        class _Faulty(BaseClass):
            def table(self, name):
                outer = self  # noqa: F841
                inner = super().table(name)
                if name == "publisher_packages":
                    def _raise():
                        raise Exception("relation 'publisher_packages' does not exist")
                    inner.execute = _raise
                return inner

        sb = _Faulty({"strategist_briefs": [_example_brief_row()]})
        pc = await load_peer_context(real_uuid, sb)
        # Brief still came through, package gracefully None.
        assert pc.latest_brief is not None
        assert pc.latest_package is None


# ── BaseAgent hydration node ──────────────────────────────────────────────
class TestBaseAgentHydration:
    async def test_merges_into_state_metadata_without_clobbering(self, real_uuid, mock_supabase_factory):
        from packages.agents.core.base import BaseAgent

        class _StubAgent(BaseAgent):
            slug = "stub"

            def build_graph(self):
                from langgraph.graph import StateGraph, END, START
                g = StateGraph(dict)
                g.add_node("a", lambda _s: {})
                g.add_edge(START, "a")
                g.add_edge("a", END)
                return g

        agent = _StubAgent()
        sb = mock_supabase_factory({"strategist_briefs": [_example_brief_row()]})
        current_supabase.set(sb)

        state = {"org_id": real_uuid, "metadata": {"existing_field": "kept"}}
        update = await agent._load_peer_context_node(state)

        assert "peer_context" in update["metadata"]
        # Pre-existing metadata must not be clobbered.
        assert update["metadata"]["existing_field"] == "kept"
        assert update["metadata"]["peer_context"]["latest_brief"]["headline"] == \
            _example_brief_row()["headline"]


# ── Strategist persist path ───────────────────────────────────────────────
class TestStrategistPersistBrief:
    async def test_writes_row_when_supabase_and_real_uuid(self, real_uuid, mock_supabase_factory):
        from packages.agents.strategist.agent import StrategistAgent

        agent = StrategistAgent()
        thread = real_uuid  # any real UUID will do
        sb = mock_supabase_factory()
        current_supabase.set(sb)

        state = {
            "org_id": real_uuid,
            "thread_id": thread,
            "brief": {
                "headline": "Test headline",
                "ideas": [{"title": "I1", "hook": "H", "why_now": "W",
                           "confidence": "high", "rationale": "R", "citations": []}],
            },
        }
        await agent._persist_brief_node(state)

        # Strategist now writes a brief row AND spawns one task per ranked
        # idea — filter to the brief insert for this assertion. Task spawning
        # has its own coverage in `test_strategist_auto_tasks.py`.
        brief_inserts = [(t, r) for t, r in sb._canned.get("_inserts", []) if t == "strategist_briefs"]
        assert len(brief_inserts) == 1
        _, payload = brief_inserts[0]
        assert payload["org_id"] == real_uuid
        assert payload["thread_id"] == thread
        assert payload["headline"] == "Test headline"
        assert len(payload["ideas"]) == 1

    async def test_noop_when_supabase_unset(self):
        """Running locally without Supabase — persist must not raise."""
        from packages.agents.strategist.agent import StrategistAgent

        agent = StrategistAgent()
        current_supabase.set(None)
        # Should complete cleanly with no exception.
        await agent._persist_brief_node({
            "org_id": "dev",
            "brief": {"headline": "x", "ideas": []},
        })


# ── Template rendering ────────────────────────────────────────────────────
class TestTemplateRendersPeerContext:
    """Templates that opt into peer_context should weave the latest brief
    headline into their output, and omit the block cleanly when absent."""

    def test_brand_manager_draft_renders_brief(self, langley_profile):
        peer = {
            "latest_brief": {
                "headline": "PEER_TEST_HEADLINE",
                "ideas": [
                    {"title": "ideatitle1"}, {"title": "ideatitle2"}, {"title": "ideatitle3"},
                ],
            },
        }
        out = render("brand_manager", "draft.j2", profile=langley_profile, peer_context=peer)
        assert "PEER_TEST_HEADLINE" in out
        assert "ideatitle1" in out

    def test_strategist_continuity_block(self, langley_profile):
        peer = {
            "latest_brief": {
                "headline": "STRAT_CONTINUITY_TEST",
                "ideas": [
                    {"title": "old1", "confidence": "high"},
                    {"title": "old2", "confidence": "medium"},
                ],
            },
        }
        sys_out = render("strategist", "system.j2", profile=langley_profile,
                         intent="weekly_brief", peer_context=peer)
        assert "STRAT_CONTINUITY_TEST" in sys_out
        assert "old1" in sys_out
        assert "old2" in sys_out

        comp_out = render("strategist", "compose_brief.j2",
                          profile=langley_profile, peer_context=peer)
        assert "STRAT_CONTINUITY_TEST" in comp_out

    def test_omits_block_when_peer_context_absent(self, langley_profile):
        # Empty dict (the dev-mode shape).
        out = render("brand_manager", "draft.j2", profile=langley_profile, peer_context={})
        assert "Strategy Context" not in out
        # Or kwarg omitted entirely.
        out2 = render("brand_manager", "draft.j2", profile=langley_profile)
        assert "Strategy Context" not in out2
