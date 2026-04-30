"""
Brand Manager auto-spawns a follow-up task when an approved pitch sends.

Same pattern as `test_strategist_auto_tasks` — mock Supabase captures
inserts across both `brand_deals` and `tasks` so we can assert the
follow-up task got created with a `deal_id` linking it to the freshly-
inserted deal row.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from packages.agents.brand_manager.agent import BrandManagerAgent
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


@pytest.fixture
def real_uuid() -> str:
    return str(uuid.uuid4())


# ── Mock Supabase capturing inserts per table ─────────────────────────────
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
        self._inserted = payload
        with_id = {"id": str(uuid.uuid4()), **payload}
        self._canned.setdefault(self._table, []).append(with_id)
        self._canned.setdefault("_inserts", []).append((self._table, with_id))
        return self

    def execute(self):
        if self._inserted is not None:
            return _MockResult([self._canned[self._table][-1]])
        return _MockResult(self._canned.get(self._table, []))


class MockSupabase:
    def __init__(self, canned: dict | None = None):
        self._canned = canned or {}

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._canned)


# ── Helper: build a state shape mirroring what the graph produces ─────────
def _state(real_uuid: str) -> dict:
    """Pre-approval-gate state, as `_send_email_node` sees it after the
    extract_email node ran upstream."""
    from langchain_core.messages import HumanMessage

    return {
        "org_id": real_uuid,
        "thread_id": real_uuid,
        "messages": [
            HumanMessage(content="draft a pitch to Magpul about the new optic line"),
        ],
        "metadata": {},
        "recipient": "marketing@magpul.com",
        "subject": "Sponsor opportunity — Langley Outdoors Academy",
        "body": "Hi Magpul team…",
    }


@pytest.mark.asyncio
class TestBmAutoFollowupTask:
    async def test_pitch_send_creates_deal_and_followup_task(self, real_uuid, monkeypatch):
        """Happy path: send_pitch_email returns success, deal logs, follow-up
        task gets created with a deal_id linking it to the deal."""
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            # agents row so create_task_from_agent can resolve agent_slug.
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "brand-manager"}],
        })
        current_supabase.set(sb)

        # Patch send_pitch_email so no real Resend call. The agent reads
        # the success-string and parses the resend id from it; we mirror
        # the real format.
        async def fake_send(*_a, **_k):
            return "Sent. Resend message id: re_mock_xyz"

        monkeypatch.setattr(
            "packages.agents.brand_manager.agent.send_pitch_email",
            type("FakeTool", (), {"ainvoke": staticmethod(fake_send)})(),
        )

        # Need a profile. _send_email_node calls self._profile(state) which
        # falls through to load_profile(state["org_id"]). With a UUID and
        # supabase set, it tries to read from org_profiles — seed one.
        sb._canned["org_profiles"] = [{
            "org_id": real_uuid,
            "brand_name": "Test Tenant",
            "brand_voice": "casual",
            "brand_primary_email": "list@test.com",
            "niche_slug": "gaming",
            "youtube_channel_id": "UC_test",
            "owners": [],
            "is_fixture": False,
        }]

        agent = BrandManagerAgent()
        update = await agent._send_email_node(_state(real_uuid))

        assert update["send_result"].startswith("Sent.")
        assert update["approval_status"] == "approved"

        inserts = sb._canned.get("_inserts", [])
        deal_inserts = [r for t, r in inserts if t == "brand_deals"]
        task_inserts = [r for t, r in inserts if t == "tasks"]

        assert len(deal_inserts) == 1, "Expected one deal row"
        assert len(task_inserts) == 1, "Expected one follow-up task row"

        deal = deal_inserts[0]
        task = task_inserts[0]

        # Task is linked to the deal we just created.
        assert task["deal_id"] == deal["id"]
        # Title carries the brand name.
        assert "Magpul" in task["title"] or "draft a pitch" in task["title"]
        assert task["status"] == "todo"
        assert task["priority"] == "medium"
        # Description includes recipient + subject.
        assert "marketing@magpul.com" in task["description"]
        assert "Sponsor opportunity" in task["description"]
        # Metadata back-link.
        assert task["metadata"]["source"] == "brand_manager_pitch"
        assert task["metadata"]["deal_id"] == deal["id"]

        # Due date is roughly 7 days out.
        due = datetime.fromisoformat(task["due_at"])
        delta = due - datetime.now(timezone.utc)
        assert timedelta(days=6) < delta < timedelta(days=8)

    async def test_dev_mode_no_writes(self, monkeypatch):
        """No supabase, dev org_id — no deal, no task. Send still succeeds."""

        async def fake_send(*_a, **_k):
            return "Sent. Resend message id: re_dev"

        monkeypatch.setattr(
            "packages.agents.brand_manager.agent.send_pitch_email",
            type("FakeTool", (), {"ainvoke": staticmethod(fake_send)})(),
        )

        agent = BrandManagerAgent()
        # No supabase set — current_supabase stays None per autouse fixture.
        # load_profile("dev") returns the demo profile without hitting DB.
        update = await agent._send_email_node({
            "org_id": "dev",
            "thread_id": "dev",
            "messages": [],
            "metadata": {},
            "recipient": "x@y.com",
            "subject": "x",
            "body": "x",
        })
        assert update["send_result"].startswith("Sent.")
        # Test passes if no exception was raised.

    async def test_followup_creation_failure_doesnt_break_the_send(self, real_uuid, monkeypatch):
        """The pitch already shipped — if task spawning blows up, the run
        must still complete successfully. Same best-effort posture as the
        deal log."""
        agent_uuid = str(uuid.uuid4())

        class _PartialFaulty(MockSupabase):
            def table(self, name):
                if name == "tasks":
                    class _BoomQuery:
                        def insert(self, _p): return self
                        def execute(self):
                            raise RuntimeError("tasks table down")
                    return _BoomQuery()
                return super().table(name)

        sb = _PartialFaulty({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "brand-manager"}],
            "org_profiles": [{
                "org_id": real_uuid, "brand_name": "Test", "owners": [], "is_fixture": False,
            }],
        })
        current_supabase.set(sb)

        async def fake_send(*_a, **_k):
            return "Sent. Resend message id: re_robust"
        monkeypatch.setattr(
            "packages.agents.brand_manager.agent.send_pitch_email",
            type("FakeTool", (), {"ainvoke": staticmethod(fake_send)})(),
        )

        agent = BrandManagerAgent()
        # Should NOT raise even though tasks insert fails.
        update = await agent._send_email_node(_state(real_uuid))
        assert update["send_result"].startswith("Sent.")
        assert update["approval_status"] == "approved"

        # Deal still logged.
        deal_inserts = [r for t, r in sb._canned.get("_inserts", []) if t == "brand_deals"]
        assert len(deal_inserts) == 1

    async def test_blank_brand_name_skips_followup(self, real_uuid, monkeypatch):
        """If the user's request was empty/whitespace (extreme edge), we
        don't try to create a 'Follow up with ' task with no subject."""
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "brand-manager"}],
            "org_profiles": [{
                "org_id": real_uuid, "brand_name": "Test", "owners": [], "is_fixture": False,
            }],
        })
        current_supabase.set(sb)

        async def fake_send(*_a, **_k):
            return "Sent. Resend message id: re_x"
        monkeypatch.setattr(
            "packages.agents.brand_manager.agent.send_pitch_email",
            type("FakeTool", (), {"ainvoke": staticmethod(fake_send)})(),
        )

        from langchain_core.messages import HumanMessage
        agent = BrandManagerAgent()
        await agent._send_email_node({
            "org_id": real_uuid,
            "thread_id": real_uuid,
            "messages": [HumanMessage(content="   ")],  # blank
            "metadata": {},
            "recipient": "x@y.com",
            "subject": "x",
            "body": "x",
        })

        task_inserts = [r for t, r in sb._canned.get("_inserts", []) if t == "tasks"]
        # Blank brand_name → log_deal_pitched skips → and the follow-up
        # _spawn_followup_task also short-circuits because brand_name is blank.
        assert len(task_inserts) == 0


@pytest.mark.asyncio
class TestSpawnFollowupTaskHelper:
    """Direct tests for `_spawn_followup_task` — easier to assert task
    fields without going through the full _send_email_node setup."""

    async def test_truncates_long_brand_name(self, real_uuid):
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "brand-manager"}],
        })
        current_supabase.set(sb)

        agent = BrandManagerAgent()
        await agent._spawn_followup_task(
            {"org_id": real_uuid, "subject": "test", "recipient": "x@y.com"},
            brand_name="A" * 200,  # excessive
            deal_id=None,
        )

        task = next(r for t, r in sb._canned["_inserts"] if t == "tasks")
        title = task["title"]
        # "Follow up with " (15) + 80 chars max = under 100.
        assert len(title) < 100
        assert title.endswith("…")

    async def test_no_deal_id_when_log_deal_returned_none(self, real_uuid):
        """When the deal log returned None (e.g. dev fallback), the
        follow-up task still gets created but with deal_id=None."""
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "brand-manager"}],
        })
        current_supabase.set(sb)

        agent = BrandManagerAgent()
        await agent._spawn_followup_task(
            {"org_id": real_uuid, "subject": "x", "recipient": "x@y.com"},
            brand_name="Magpul",
            deal_id=None,
        )

        task = next(r for t, r in sb._canned["_inserts"] if t == "tasks")
        assert task["deal_id"] is None

    async def test_handles_missing_subject_and_recipient(self, real_uuid):
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "brand-manager"}],
        })
        current_supabase.set(sb)

        agent = BrandManagerAgent()
        await agent._spawn_followup_task(
            {"org_id": real_uuid},  # no subject, no recipient
            brand_name="Magpul",
            deal_id=None,
        )

        task = next(r for t, r in sb._canned["_inserts"] if t == "tasks")
        # Description should still be useful even without subject/recipient.
        assert "Check for response" in task["description"]
        # Empty fields shouldn't appear as "To: " / "Subject: " lines.
        assert "To: " not in task["description"]
        assert "Subject: " not in task["description"]
