"""
Brand Manager deal pipeline — `log_deal_pitched`, `list_active_deals`,
auto-log on `_send_email_node`, and the peer_context wiring.

No live Postgres or Resend — uses a hand-rolled MockSupabase to capture
inserts and serve canned rows.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from packages.agents.brand_manager.deals import (
    _extract_resend_id,
    list_active_deals,
    log_deal_pitched,
)
from packages.agents.core.peer_context import (
    DealSummary,
    PeerContext,
    load_peer_context,
)
from packages.integrations.context import (
    current_org_id,
    current_supabase,
    current_user_id,
)


@pytest.fixture(autouse=True)
def _reset_contextvars():
    current_org_id.set(None)
    current_user_id.set(None)
    current_supabase.set(None)
    yield
    current_org_id.set(None)
    current_user_id.set(None)
    current_supabase.set(None)


@pytest.fixture
def real_uuid() -> str:
    return str(uuid.uuid4())


# ── MockSupabase (canned reads + capture writes) ──────────────────────────
class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    def __init__(self, table_name: str, canned: dict):
        self._table = table_name
        self._canned = canned
        self._inserted: dict | None = None

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def insert(self, payload: dict):
        # Capture the insert for later assertions, and append to the
        # canned rows so subsequent reads see it.
        self._inserted = payload
        # Add a synthesized id so tests can read it back.
        with_id = {"id": str(uuid.uuid4()), **payload}
        self._canned.setdefault(self._table, []).append(with_id)
        self._canned.setdefault("_inserts", []).append((self._table, with_id))
        return self

    def execute(self):
        if self._inserted is not None:
            # insert().execute() returns the inserted row
            return _MockResult([self._canned[self._table][-1]])
        return _MockResult(self._canned.get(self._table, []))


class MockSupabase:
    def __init__(self, canned: dict | None = None):
        self._canned = canned or {}

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._canned)


# ── _extract_resend_id ────────────────────────────────────────────────────
class TestExtractResendId:
    @pytest.mark.parametrize("input_str, expected", [
        ("Sent. Resend message id: re_abc123", "re_abc123"),
        ("Sent. Resend message id: 1234abcd-5678", "1234abcd-5678"),
        ("Send failed: foo", None),
        (None, None),
        ("", None),
    ])
    def test_parses(self, input_str, expected):
        assert _extract_resend_id(input_str) == expected


# ── log_deal_pitched ──────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestLogDealPitched:
    async def test_inserts_row_when_org_real_and_supabase_set(self, real_uuid):
        sb = MockSupabase()
        current_supabase.set(sb)

        deal_id = await log_deal_pitched(
            org_id=real_uuid,
            thread_id=real_uuid,
            brand_name="Magpul",
            recipient="marketing@magpul.com",
            subject="Sponsor opportunity — Langley",
            send_result="Sent. Resend message id: re_test_xyz",
        )

        assert deal_id is not None
        inserts = sb._canned["_inserts"]
        assert len(inserts) == 1
        table, row = inserts[0]
        assert table == "brand_deals"
        assert row["org_id"] == real_uuid
        assert row["thread_id"] == real_uuid
        assert row["brand_name"] == "Magpul"
        assert row["recipient"] == "marketing@magpul.com"
        assert row["subject"] == "Sponsor opportunity — Langley"
        assert row["stage"] == "pitched"
        assert row["external_message_id"] == "re_test_xyz"

    async def test_noop_in_dev_mode(self):
        # No supabase set, no org_id — should be a clean no-op.
        result = await log_deal_pitched(
            org_id="dev",
            thread_id=None,
            brand_name="Magpul",
            recipient="x@y.com",
            subject="x",
            send_result="Sent.",
        )
        assert result is None

    async def test_noop_when_org_id_not_uuid(self):
        sb = MockSupabase()
        current_supabase.set(sb)
        # Even with Supabase set, "dev" string org_id should skip.
        result = await log_deal_pitched(
            org_id="dev",
            thread_id=None,
            brand_name="Magpul",
            recipient="x@y.com",
            subject="x",
            send_result="Sent.",
        )
        assert result is None
        assert "_inserts" not in sb._canned

    async def test_noop_when_brand_name_blank(self, real_uuid):
        sb = MockSupabase()
        current_supabase.set(sb)
        result = await log_deal_pitched(
            org_id=real_uuid,
            thread_id=None,
            brand_name="   ",
            recipient="x@y.com",
            subject="x",
            send_result="Sent.",
        )
        assert result is None
        assert "_inserts" not in sb._canned

    async def test_db_error_does_not_raise(self, real_uuid):
        """A failed insert must not break the agent run — the email
        already shipped, pipeline bookkeeping is best-effort."""

        class _ExplodingSupabase(MockSupabase):
            def table(self, name):
                raise RuntimeError("DB down")

        current_supabase.set(_ExplodingSupabase())
        # Should NOT raise.
        result = await log_deal_pitched(
            org_id=real_uuid,
            thread_id=None,
            brand_name="Magpul",
            recipient="x@y.com",
            subject="x",
            send_result="Sent.",
        )
        assert result is None


# ── list_active_deals ─────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestListActiveDeals:
    async def test_returns_rows_for_real_org(self, real_uuid):
        canned = {
            "brand_deals": [
                {
                    "id": "1",
                    "brand_name": "Magpul",
                    "stage": "negotiating",
                    "recipient": "marketing@magpul.com",
                    "last_updated_at": "2026-04-25T12:00:00Z",
                },
                {
                    "id": "2",
                    "brand_name": "Vortex Optics",
                    "stage": "pitched",
                    "recipient": "media@vortex.com",
                    "last_updated_at": "2026-04-23T09:30:00Z",
                },
            ],
        }
        sb = MockSupabase(canned)
        deals = await list_active_deals(org_id=real_uuid, supabase=sb)
        assert len(deals) == 2
        assert deals[0]["brand_name"] == "Magpul"

    async def test_dev_org_returns_empty(self):
        sb = MockSupabase({"brand_deals": [{"brand_name": "X", "stage": "pitched"}]})
        deals = await list_active_deals(org_id="dev", supabase=sb)
        assert deals == []

    async def test_no_supabase_returns_empty(self, real_uuid):
        deals = await list_active_deals(org_id=real_uuid, supabase=None)
        assert deals == []

    async def test_db_error_returns_empty(self, real_uuid):
        class _Faulty(MockSupabase):
            def table(self, name):
                raise RuntimeError("nope")
        deals = await list_active_deals(org_id=real_uuid, supabase=_Faulty())
        assert deals == []

    async def test_uses_contextvar_when_supabase_omitted(self, real_uuid):
        sb = MockSupabase({"brand_deals": [
            {"brand_name": "Magpul", "stage": "pitched", "last_updated_at": "2026-04-25"}
        ]})
        current_supabase.set(sb)
        deals = await list_active_deals(org_id=real_uuid)  # supabase=None default
        assert len(deals) == 1


# ── peer_context.active_deals wiring ──────────────────────────────────────
@pytest.mark.asyncio
class TestPeerContextActiveDeals:
    async def test_loader_populates_active_deals(self, real_uuid):
        canned = {
            "brand_deals": [
                {"brand_name": "Magpul", "stage": "negotiating",
                 "recipient": "m@magpul.com", "last_updated_at": "2026-04-25"},
                {"brand_name": "Vortex", "stage": "pitched",
                 "recipient": None, "last_updated_at": "2026-04-23"},
            ],
        }
        pc = await load_peer_context(real_uuid, MockSupabase(canned))
        assert len(pc.active_deals) == 2
        assert isinstance(pc.active_deals[0], DealSummary)
        assert pc.active_deals[0].brand_name == "Magpul"
        assert pc.active_deals[0].stage == "negotiating"
        assert pc.has_any()

    async def test_missing_brand_deals_table_does_not_raise(self, real_uuid):
        """Mirrors the publisher_packages graceful-fallback pattern. If
        the brand_deals table doesn't exist (pre-migration env), the
        loader returns active_deals=[] rather than crashing."""
        class _NoTable(MockSupabase):
            def table(self, name):
                if name == "brand_deals":
                    class _Boom:
                        def select(self, *_a, **_k): return self
                        def eq(self, *_a, **_k): return self
                        def order(self, *_a, **_k): return self
                        def limit(self, *_a, **_k): return self
                        def execute(self):
                            raise Exception("relation 'brand_deals' does not exist")
                    return _Boom()
                return super().table(name)

        pc = await load_peer_context(real_uuid, _NoTable())
        assert pc.active_deals == []

    async def test_dev_org_returns_empty_peer_context(self):
        pc = await load_peer_context("dev", MockSupabase({"brand_deals": [{}]}))
        assert pc.active_deals == []


# ── Template rendering — research_or_leads.j2 ─────────────────────────────
class TestPipelineRendersInTemplate:
    """Templates assume peer_context is a complete `PeerContext.model_dump()`
    shape (the production path always passes that — see
    BaseAgent._load_peer_context_node). Tests construct the same shape via
    `PeerContext(...).model_dump(mode="json")` to mirror reality."""

    def test_pipeline_section_appears_when_deals_present(self):
        from packages.agents.core.templates import render
        from packages.agents.core.profile import load_profile

        p = load_profile("langley-outdoors-academy")
        peer = PeerContext(
            active_deals=[
                DealSummary(brand_name="Magpul", stage="negotiating",
                            recipient="m@magpul.com", last_updated_at="2026-04-25"),
                DealSummary(brand_name="Vortex", stage="pitched",
                            recipient=None, last_updated_at="2026-04-23"),
            ],
        ).model_dump(mode="json")

        out = render("brand_manager", "research_or_leads.j2",
                     profile=p, peer_context=peer)
        assert "Active Deal Pipeline" in out
        assert "Magpul" in out and "negotiating" in out
        assert "Vortex" in out and "pitched" in out

    def test_pipeline_section_omitted_when_no_deals(self):
        from packages.agents.core.templates import render
        from packages.agents.core.profile import load_profile

        p = load_profile("langley-outdoors-academy")
        peer = PeerContext().model_dump(mode="json")  # all empty
        out = render("brand_manager", "research_or_leads.j2",
                     profile=p, peer_context=peer)
        assert "Active Deal Pipeline" not in out


# ── _send_email_node auto-logs the deal ───────────────────────────────────
@pytest.mark.asyncio
class TestSendEmailAutoLogs:
    async def test_pitched_row_inserted_after_send(self, real_uuid, monkeypatch):
        """End-to-end-ish: invoke `_send_email_node` with mocked Resend
        and verify a brand_deals row gets logged with the right shape."""
        from packages.agents.brand_manager.agent import BrandManagerAgent
        from langchain_core.messages import HumanMessage

        agent = BrandManagerAgent()
        # Seed an `org_profiles` row so `_send_email_node`'s `_profile()`
        # call succeeds (load_profile raises ProfileNotFound otherwise).
        sb = MockSupabase({
            "org_profiles": [{
                "org_id": real_uuid,
                "brand_name": "Test Tenant",
                "brand_voice": "casual, professional",
                "brand_primary_email": "list@test.com",
                "niche_slug": "gaming",
                "youtube_channel_id": "UC_test",
                "owners": [],
                "is_fixture": False,
            }],
        })
        current_supabase.set(sb)

        # Patch the send_pitch_email tool so no real Resend call.
        async def fake_send(*a, **k):
            return "Sent. Resend message id: re_mock_xyz"

        # The tool is bound on the agent's class via `await tool.ainvoke(...)`,
        # so monkey-patch the module function the tool wraps. Easiest: patch
        # the imported reference in the agent module.
        monkeypatch.setattr(
            "packages.agents.brand_manager.agent.send_pitch_email",
            type("FakeTool", (), {"ainvoke": staticmethod(fake_send)})(),
        )

        state = {
            "org_id": real_uuid,
            "thread_id": real_uuid,
            "messages": [HumanMessage(content="draft a pitch to Magpul about the new optic line")],
            "metadata": {},
            "recipient": "marketing@magpul.com",
            "subject": "Sponsor opportunity — Langley Outdoors Academy",
            "body": "Hi Magpul team...",
        }
        update = await agent._send_email_node(state)

        assert update["send_result"].startswith("Sent.")
        assert update["approval_status"] == "approved"

        # And a deal row got inserted
        inserts = sb._canned.get("_inserts", [])
        assert len(inserts) == 1
        table, row = inserts[0]
        assert table == "brand_deals"
        assert row["stage"] == "pitched"
        # brand_name comes from the user's request verbatim
        assert "Magpul" in row["brand_name"]
        assert row["recipient"] == "marketing@magpul.com"
        assert row["external_message_id"] == "re_mock_xyz"
