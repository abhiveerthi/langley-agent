"""
Content Agent Phase C — Monday review queue + two-tier decision engine.

No network, no live Monday. Covers:
  - label → decision mapping (text-matched, case-insensitive)
  - item naming per asset kind
  - apply_status_change: asset decisions mirror onto pipeline assets;
    FINAL item drives ready_for_review → approved / rejected / reopened
  - unknown items and foreign labels are ignored (webhook noise safety)
  - webhook router: secret gate, challenge handshake, event routing
"""
from __future__ import annotations

import pytest

from packages.agents.content import review


# ── Label mapping + naming ─────────────────────────────────────────────────
class TestLabelMapping:
    @pytest.mark.parametrize("label, expected", [
        ("Approved", "approved"),
        ("approved", "approved"),
        ("  Rejected ", "rejected"),
        ("Pending Review", "pending"),
        ("Working on it", None),   # foreign label → ignore
        (None, None),
        ("", None),
    ])
    def test_decision_for_label(self, label, expected):
        assert review.decision_for_label(label) == expected

    def test_item_names(self):
        assert review.item_name_for_asset({"kind": "clip", "title": "Hook"}, 0) == "[Clip] Hook"
        assert review.item_name_for_asset({"kind": "podcast_episode", "title": "Ep 9"}, 1) == "[Podcast] Ep 9"
        assert review.item_name_for_asset({"kind": "audio", "storage_path": "p/a.m4a"}, 2) == "[Audio] p/a.m4a"
        assert review.item_name_for_asset({"kind": "mystery"}, 3) == "[Asset] #4"


# ── Decision engine ────────────────────────────────────────────────────────
def _canned(role="asset", asset_index=0, decision="pending"):
    return {
        "content_review_items": [{
            "org_id": "org-1", "video_id": "vidZ", "monday_item_id": "111",
            "role": role, "asset_index": asset_index, "kind": "clip",
            "decision": decision,
        }],
        "content_pipelines": [{
            "org_id": "org-1", "video_id": "vidZ", "status": "ready_for_review",
            "assets": [{"kind": "clip", "url": "https://c/1.mp4"}],
        }],
    }


class TestApplyStatusChange:
    def test_asset_approval_mirrors_onto_pipeline_assets(self, mock_supabase_factory):
        sb = mock_supabase_factory(_canned())
        got = review.apply_status_change(sb, "org-1", monday_item_id="111", label="Approved")
        assert got == {"role": "asset", "decision": "approved", "video_id": "vidZ"}
        updates = sb._canned.get("_updates", [])
        # 1) review item row, 2) pipeline assets mirror
        tables = [t for t, _ in updates]
        assert tables == ["content_review_items", "content_pipelines"]
        assert updates[1][1]["assets"][0]["approved"] is True

    def test_asset_rejection_marks_false(self, mock_supabase_factory):
        sb = mock_supabase_factory(_canned())
        review.apply_status_change(sb, "org-1", monday_item_id="111", label="Rejected")
        updates = sb._canned.get("_updates", [])
        assert updates[1][1]["assets"][0]["approved"] is False

    def test_final_approval_advances_pipeline(self, mock_supabase_factory):
        sb = mock_supabase_factory(_canned(role="final", asset_index=None))
        got = review.apply_status_change(sb, "org-1", monday_item_id="111", label="Approved")
        assert got["role"] == "final"
        pipeline_updates = [p for t, p in sb._canned["_updates"] if t == "content_pipelines"]
        assert pipeline_updates and pipeline_updates[-1]["status"] == "approved"

    def test_final_rejection_kills_the_drop(self, mock_supabase_factory):
        sb = mock_supabase_factory(_canned(role="final", asset_index=None))
        review.apply_status_change(sb, "org-1", monday_item_id="111", label="Rejected")
        pipeline_updates = [p for t, p in sb._canned["_updates"] if t == "content_pipelines"]
        assert pipeline_updates[-1]["status"] == "rejected"
        assert "final approval" in pipeline_updates[-1]["error"]

    def test_final_reopen_returns_to_review(self, mock_supabase_factory):
        canned = _canned(role="final", asset_index=None, decision="approved")
        canned["content_pipelines"][0]["status"] = "approved"  # reopen only from a decided state
        sb = mock_supabase_factory(canned)
        review.apply_status_change(sb, "org-1", monday_item_id="111", label="Pending Review")
        pipeline_updates = [p for t, p in sb._canned["_updates"] if t == "content_pipelines"]
        assert pipeline_updates[-1]["status"] == "ready_for_review"

    def test_unknown_item_ignored(self, mock_supabase_factory):
        sb = mock_supabase_factory({"content_review_items": []})
        assert review.apply_status_change(sb, "org-1", monday_item_id="999", label="Approved") is None
        assert "_updates" not in sb._canned

    def test_foreign_label_ignored(self, mock_supabase_factory):
        sb = mock_supabase_factory(_canned())
        assert review.apply_status_change(sb, "org-1", monday_item_id="111", label="Stuck") is None
        assert "_updates" not in sb._canned


# ── Webhook router ─────────────────────────────────────────────────────────
ORG = "8b7d2c31-4a5e-4f6a-9c8d-1e2f3a4b5c6d"  # org_id must be a real UUID now


class _FakeRequest:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _sb_with_secret(mock_supabase_factory, secret="s3cret", status_column_id="status_x", extra=None):
    canned = {
        # Service-role-only provisioning table (NOT agents.config — that's
        # member-readable and must never carry the webhook secret).
        "content_review_boards": [{
            "org_id": ORG, "board_id": "b1",
            "status_column_id": status_column_id,
            "webhook_id": "w1", "webhook_secret": secret,
        }],
    }
    canned.update(extra or {})
    return mock_supabase_factory(canned)


class TestWebhookRouter:
    @pytest.mark.asyncio
    async def test_wrong_secret_is_404(self, mock_supabase_factory, monkeypatch):
        from app.routers import monday_webhooks as mw
        from fastapi import HTTPException

        sb = _sb_with_secret(mock_supabase_factory, secret="right")
        monkeypatch.setattr(mw, "_service_client", lambda: sb)
        with pytest.raises(HTTPException) as ei:
            await mw.monday_webhook(ORG, "wrong", _FakeRequest({"challenge": "x"}))
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_non_uuid_org_rejected_before_any_db_work(self, monkeypatch):
        from app.routers import monday_webhooks as mw
        from fastapi import HTTPException

        def _explodes():
            raise AssertionError("DB must not be touched for a non-UUID org id")

        monkeypatch.setattr(mw, "_service_client", _explodes)
        with pytest.raises(HTTPException) as ei:
            await mw.monday_webhook("not-a-uuid", "s", _FakeRequest({}))
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_oversized_body_rejected(self, mock_supabase_factory, monkeypatch):
        from app.routers import monday_webhooks as mw
        from fastapi import HTTPException

        sb = _sb_with_secret(mock_supabase_factory)
        monkeypatch.setattr(mw, "_service_client", lambda: sb)
        with pytest.raises(HTTPException) as ei:
            await mw.monday_webhook(
                ORG, "s3cret",
                _FakeRequest({}, headers={"content-length": str(10_000_000)}),
            )
        assert ei.value.status_code == 413

    @pytest.mark.asyncio
    async def test_challenge_echo(self, mock_supabase_factory, monkeypatch):
        from app.routers import monday_webhooks as mw

        sb = _sb_with_secret(mock_supabase_factory)
        monkeypatch.setattr(mw, "_service_client", lambda: sb)
        got = await mw.monday_webhook(ORG, "s3cret", _FakeRequest({"challenge": "abc123"}))
        assert got == {"challenge": "abc123"}

    @pytest.mark.asyncio
    async def test_status_event_applies_decision(self, mock_supabase_factory, monkeypatch):
        from app.routers import monday_webhooks as mw

        sb = _sb_with_secret(mock_supabase_factory, extra=_canned())
        monkeypatch.setattr(mw, "_service_client", lambda: sb)
        body = {
            "event": {
                "type": "update_column_value",
                "pulseId": 111,
                "columnId": "status_x",
                "value": {"label": {"text": "Approved"}},
            }
        }
        got = await mw.monday_webhook(ORG, "s3cret", _FakeRequest(body))
        assert got["applied"] is True
        tables = [t for t, _ in sb._canned["_updates"]]
        assert "content_review_items" in tables

    @pytest.mark.asyncio
    async def test_other_status_columns_ignored(self, mock_supabase_factory, monkeypatch):
        """A second status column on the board (user-added 'Status', etc.)
        must never drive review decisions, even with matching label text."""
        from app.routers import monday_webhooks as mw

        sb = _sb_with_secret(mock_supabase_factory, extra=_canned())
        monkeypatch.setattr(mw, "_service_client", lambda: sb)
        body = {
            "event": {
                "type": "update_column_value",
                "pulseId": 111,
                "columnId": "some_other_column",
                "value": {"label": {"text": "Approved"}},
            }
        }
        got = await mw.monday_webhook(ORG, "s3cret", _FakeRequest(body))
        assert got["ignored"] == "column some_other_column"
        assert "_updates" not in sb._canned

    @pytest.mark.asyncio
    async def test_non_column_events_ignored(self, mock_supabase_factory, monkeypatch):
        from app.routers import monday_webhooks as mw

        sb = _sb_with_secret(mock_supabase_factory)
        monkeypatch.setattr(mw, "_service_client", lambda: sb)
        got = await mw.monday_webhook(
            ORG, "s3cret", _FakeRequest({"event": {"type": "create_pulse"}})
        )
        assert got["ignored"] == "create_pulse"


# ── FINAL-gate transition guards ───────────────────────────────────────────
class TestFinalGateGuards:
    def _sb(self, mock_supabase_factory, pipeline_status):
        canned = _canned(role="final", asset_index=None)
        canned["content_pipelines"][0]["status"] = pipeline_status
        return mock_supabase_factory(canned)

    @pytest.mark.parametrize("current, label, expect_status", [
        ("ready_for_review", "Approved", "approved"),
        ("rejected", "Approved", "approved"),        # owner changed his mind
        ("approved", "Rejected", "rejected"),         # pre-publish kill
        ("approved", "Pending Review", "ready_for_review"),
    ])
    def test_allowed_transitions(self, mock_supabase_factory, current, label, expect_status):
        sb = self._sb(mock_supabase_factory, current)
        review.apply_status_change(sb, "org-1", monday_item_id="111", label=label)
        pipeline_updates = [p for t, p in sb._canned["_updates"] if t == "content_pipelines"]
        assert pipeline_updates and pipeline_updates[-1]["status"] == expect_status

    @pytest.mark.parametrize("current, label", [
        ("published", "Pending Review"),   # never rewind a live drop
        ("publishing", "Rejected"),        # too late — fan-out in flight
        ("processing", "Approved"),        # re-run mid-flight
        ("failed", "Approved"),            # nothing to approve
    ])
    def test_blocked_transitions_leave_pipeline_untouched(self, mock_supabase_factory, current, label):
        sb = self._sb(mock_supabase_factory, current)
        review.apply_status_change(sb, "org-1", monday_item_id="111", label=label)
        pipeline_updates = [p for t, p in sb._canned.get("_updates", []) if t == "content_pipelines"]
        assert pipeline_updates == []  # item decision recorded, pipeline untouched

    def test_reapproval_clears_prior_rejection_error(self, mock_supabase_factory):
        sb = self._sb(mock_supabase_factory, "rejected")
        review.apply_status_change(sb, "org-1", monday_item_id="111", label="Approved")
        pipeline_updates = [p for t, p in sb._canned["_updates"] if t == "content_pipelines"]
        assert pipeline_updates[-1]["error"] is None


# ── queue_for_review degrades without Monday ───────────────────────────────
class TestQueueForReview:
    @pytest.mark.asyncio
    async def test_dev_mode_note(self):
        # current_supabase is None (autouse reset) → ledger-only note.
        note = await review.queue_for_review(
            "dev", video_id="v", video_title="t", assets=[{"kind": "clip"}]
        )
        assert "dev mode" in note
