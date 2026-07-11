"""
Agent #7 (B-Roll) daily-production automation. No LLM, no Higgsfield, no
Dropbox, no live Supabase. Covers:

  - is_due: one run per UTC day
  - the sweep's gates (Higgsfield unconfigured / opt-out / already ran /
    in-flight) and the day-claim before spawning
  - run_daily_production orchestration with drafting/rendering seams faked:
    target honored, batch task filed, mostly-failed day escalates
  - the set_direction chat node: prefix stripping + config merge (sibling
    keys survive)
  - fetch_recent_image_insights dev no-op
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.services import broll_production as bp


# ── is_due ─────────────────────────────────────────────────────────────────
class TestIsDue:
    NOW = datetime(2026, 7, 11, 15, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize("last, due", [
        (None, True),
        ("", True),
        ("garbage", True),
        ("2026-07-10T23:59:00+00:00", True),   # yesterday
        ("2026-07-11T00:01:00+00:00", False),  # already ran today
        ("2026-07-11T14:59:00Z", False),
    ])
    def test_matrix(self, last, due):
        assert bp.is_due(last, now=self.NOW) is due


# ── Sweep gating ───────────────────────────────────────────────────────────
class TestSweep:
    def _agents_row(self, org, enabled=True, direction="pro-America, sarcasm"):
        return {"org_id": org, "config": {
            "daily_production_enabled": enabled,
            "weekly_direction": direction,
        }}

    @pytest.mark.asyncio
    async def test_skips_entirely_without_higgsfield(self, mock_supabase_factory, monkeypatch):
        # HIGGSFIELD_API_KEY is scrubbed by conftest → is_configured False.
        sb = mock_supabase_factory({"agents": [self._agents_row("org-1")]})
        ran = []
        monkeypatch.setattr(bp, "_run_wrapper", lambda *a: ran.append(a))
        await bp.broll_daily_sweep(sb)
        assert ran == []
        assert "_upserts" not in sb._canned

    @pytest.mark.asyncio
    async def test_due_org_is_claimed_and_spawned(self, mock_supabase_factory, monkeypatch):
        import packages.integrations.higgsfield as hf

        monkeypatch.setattr(hf, "is_configured", lambda: True)
        monkeypatch.setattr(bp, "_dropbox_ready", lambda sb, org: True)
        sb = mock_supabase_factory({
            "agents": [self._agents_row("org-1")],
            "scheduled_jobs": [],  # never ran → due
        })
        ran = []

        async def fake_run(supabase, org_id, config):
            ran.append(org_id)

        monkeypatch.setattr(bp, "_run_wrapper", fake_run)
        await bp.broll_daily_sweep(sb)
        await asyncio.sleep(0)  # let the spawned task tick

        assert ran == ["org-1"]
        # Atomic claim: no stale row existed → the claim lands as an INSERT
        # with the day started and status=running.
        claims = [p for t, p in sb._canned.get("_inserts", []) if t == "scheduled_jobs"]
        assert claims and claims[0]["kind"] == bp.JOB_KIND
        assert claims[0]["last_run_at"] and claims[0]["last_status"] == "running"

    @pytest.mark.asyncio
    async def test_sweep_skips_without_direction_or_dropbox(self, mock_supabase_factory, monkeypatch):
        """Spend gates: no weekly_direction, or no Dropbox, must skip BEFORE
        any claim — rendering into the void costs real money."""
        import packages.integrations.higgsfield as hf

        monkeypatch.setattr(hf, "is_configured", lambda: True)
        ran = []

        async def fake_run(supabase, org_id, config):
            ran.append(org_id)

        monkeypatch.setattr(bp, "_run_wrapper", fake_run)

        # No direction (dropbox fine)
        monkeypatch.setattr(bp, "_dropbox_ready", lambda sb, org: True)
        sb = mock_supabase_factory({"agents": [self._agents_row("org-1", direction="")]})
        await bp.broll_daily_sweep(sb)
        # Direction fine, no dropbox
        monkeypatch.setattr(bp, "_dropbox_ready", lambda sb, org: False)
        sb2 = mock_supabase_factory({"agents": [self._agents_row("org-2")]})
        await bp.broll_daily_sweep(sb2)
        await asyncio.sleep(0)

        assert ran == []
        assert "_inserts" not in sb._canned and "_inserts" not in sb2._canned

    @pytest.mark.asyncio
    async def test_opted_out_and_already_ran_orgs_skipped(self, mock_supabase_factory, monkeypatch):
        import packages.integrations.higgsfield as hf

        monkeypatch.setattr(hf, "is_configured", lambda: True)
        today = datetime.now(timezone.utc).isoformat()
        sb = mock_supabase_factory({
            "agents": [self._agents_row("org-out", enabled=False)],
            "scheduled_jobs": [{"last_run_at": today}],
        })
        ran = []

        async def fake_run(supabase, org_id):
            ran.append(org_id)

        monkeypatch.setattr(bp, "_run_wrapper", fake_run)
        await bp.broll_daily_sweep(sb)
        await asyncio.sleep(0)
        assert ran == []

    @pytest.mark.asyncio
    async def test_inflight_org_not_double_spawned(self, mock_supabase_factory, monkeypatch):
        import packages.integrations.higgsfield as hf

        monkeypatch.setattr(hf, "is_configured", lambda: True)
        sb = mock_supabase_factory({"agents": [self._agents_row("org-1")]})
        ran = []

        async def fake_run(supabase, org_id):
            ran.append(org_id)

        monkeypatch.setattr(bp, "_run_wrapper", fake_run)
        bp._inflight.add("org-1")
        try:
            await bp.broll_daily_sweep(sb)
            await asyncio.sleep(0)
            assert ran == []
        finally:
            bp._inflight.discard("org-1")


# ── run_daily_production orchestration ─────────────────────────────────────
class TestRunDailyProduction:
    DEFAULT_CONFIG = {"daily_clip_target": 5, "weekly_direction": "debate fallout, keep it light"}

    def _sb(self, mock_supabase_factory):
        return mock_supabase_factory({})

    @pytest.fixture
    def seams(self, monkeypatch):
        calls = {"draft": [], "render": [], "tasks": [], "alerts": []}

        async def fake_draft(org_id, *, direction, insight_block, target, default_aspect):
            calls["draft"].append({"direction": direction, "target": target})
            return [{"prompt": f"p{i}", "topic": "T"} for i in range(target)]

        async def fake_render(org_id, specs, *, default_aspect):
            calls["render"].append(len(specs))
            return len(specs), 0  # all deposited

        async def fake_task(**kw):
            calls["tasks"].append(kw)
            return "task-1"

        async def fake_insights(org_id, limit=5):
            return ["competitor momentum insight"]

        monkeypatch.setattr(bp, "_draft_all", fake_draft)
        monkeypatch.setattr(bp, "_render_and_deposit", fake_render)
        import packages.agents.broll.tools as bt
        import packages.agents.core.tasks as core_tasks

        monkeypatch.setattr(core_tasks, "create_task_from_agent", fake_task)
        monkeypatch.setattr(bt, "fetch_recent_image_insights", fake_insights)
        import packages.agents.content.alerts as alerts

        async def fake_escalate(org_id, msg, *, supabase=None):
            calls["alerts"].append(msg)
            return True

        monkeypatch.setattr(alerts, "escalate", fake_escalate)
        return calls

    @pytest.mark.asyncio
    async def test_happy_path_files_summary_task(self, mock_supabase_factory, seams):
        sb = self._sb(mock_supabase_factory)
        summary = await bp.run_daily_production(sb, "o", dict(self.DEFAULT_CONFIG))
        assert "5/5 clips deposited" in summary
        assert seams["draft"][0]["target"] == 5
        assert "debate fallout" in seams["draft"][0]["direction"]
        assert seams["tasks"] and "5 clips ready" in seams["tasks"][0]["title"]
        assert seams["alerts"] == []

    @pytest.mark.asyncio
    async def test_target_clamped_to_max(self, mock_supabase_factory, seams):
        sb = self._sb(mock_supabase_factory)
        await bp.run_daily_production(sb, "o", {"daily_clip_target": 5000, "weekly_direction": "d"})
        assert seams["draft"][0]["target"] == bp.MAX_DAILY_TARGET

    @pytest.mark.asyncio
    async def test_mostly_failed_day_escalates(self, mock_supabase_factory, seams, monkeypatch):
        async def bad_render(org_id, specs, *, default_aspect):
            return 1, len(specs) - 1  # 1 ok, rest failed

        monkeypatch.setattr(bp, "_render_and_deposit", bad_render)
        sb = self._sb(mock_supabase_factory)
        summary = await bp.run_daily_production(sb, "o", dict(self.DEFAULT_CONFIG))
        assert "failed" in summary
        assert seams["alerts"] and "mostly failed" in seams["alerts"][0]


# ── set_direction chat node ────────────────────────────────────────────────
class TestSetDirection:
    @pytest.mark.asyncio
    async def test_saves_merged_config_and_strips_prefix(
        self, mock_supabase_factory, real_uuid
    ):
        from langchain_core.messages import HumanMessage
        from packages.agents.broll.agent import BRollAgent
        from packages.integrations.context import current_supabase

        sb = mock_supabase_factory({
            "agents": [{"slug": "broll",
                        "config": {"daily_clip_target": 80, "daily_production_enabled": True}}],
        })
        current_supabase.set(sb)
        agent = BRollAgent()
        state = {
            "messages": [HumanMessage(content="This week's direction: pro-America angles, heavy sarcasm")],
            "org_id": real_uuid,
            "metadata": {},
        }
        out = await agent._set_direction_node(state)
        assert "Locked in" in out["messages"][0].content

        updates = [p for t, p in sb._canned["_updates"] if t == "agents"]
        assert updates, "config update must be written"
        cfg = updates[0]["config"]
        assert cfg["weekly_direction"] == "pro-America angles, heavy sarcasm"
        assert cfg["daily_clip_target"] == 80          # sibling keys survive
        assert cfg["daily_production_enabled"] is True
        assert cfg["direction_updated_at"]

    @pytest.mark.asyncio
    async def test_dev_mode_reports_not_persisted(self):
        from langchain_core.messages import HumanMessage
        from packages.agents.broll.agent import BRollAgent

        agent = BRollAgent()
        out = await agent._set_direction_node({
            "messages": [HumanMessage(content="direction: lighter, funnier")],
            "org_id": "dev",
            "metadata": {},
        })
        assert "couldn't" in out["messages"][0].content.lower()


# ── Cross-agent insight feed ───────────────────────────────────────────────
class TestInsightFeed:
    @pytest.mark.asyncio
    async def test_dev_noop(self):
        from packages.agents.broll.tools import fetch_recent_image_insights

        assert await fetch_recent_image_insights("dev") == []
