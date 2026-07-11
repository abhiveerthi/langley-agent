"""
Unit tests for the background scheduler / YouTube new-upload poller.

No live network. The YouTube client is mocked at the module boundary the
scheduler imports it from. Covers:

  - `is_new_upload` decision matrix (the pure core)
  - poller no-ops when no YouTube connection exists
  - first-ever poll records the head WITHOUT dispatching Publisher
  - a genuinely new upload triggers the Publisher create_package dispatch
  - importing the FastAPI app does NOT spawn the poll loop
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import scheduler


# ── Pure decision logic ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "last_seen, latest, expected",
    [
        (None, None, False),            # empty channel, never polled
        (None, "vid1", False),          # first poll → record head, don't fire
        ("vid1", None, False),          # lookup returned nothing → not new
        ("vid1", "vid1", False),        # unchanged head → not new
        ("vid1", "vid2", True),         # new upload → fire
        ("", "vid2", False),            # empty-string last_seen == first poll
        ("vid1", "", False),            # empty latest → not new
    ],
)
def test_is_new_upload(last_seen, latest, expected):
    assert scheduler.is_new_upload(last_seen, latest) is expected


# ── Mock YouTube client ─────────────────────────────────────────────────────

class _FakeYT:
    """Stand-in for packages.integrations.youtube.client used by the poller.

    `connection` is what get_connection returns (None = not connected).
    `recent` is the newest-first page get_recent_uploads returns (pass
    `latest` for the common single-head case). `dispatched` records calls so
    tests can assert the Publisher flow did/didn't fire — without monkeypatching
    the whole orchestrator we instead intercept get_recent_uploads + the
    publisher dispatch via the supabase mock's recorded inserts.
    """

    def __init__(self, connection=None, latest=None, recent=None):
        self.connection = connection
        self.recent = recent if recent is not None else ([latest] if latest else [])
        self.token_calls = 0

    def get_connection(self, supabase, org_id):
        return self.connection

    async def get_fresh_access_token(self, supabase, org_id, cid, csecret):
        self.token_calls += 1
        return "fake-access-token"

    async def get_recent_uploads(self, access_token, uploads_playlist_id, *, limit=10):
        return self.recent[:limit]


@pytest.fixture
def patch_yt(monkeypatch):
    """Install a _FakeYT as the scheduler's `yt` module. The scheduler imports
    the client lazily inside _poll_org (`from packages.integrations.youtube
    import client as yt`), so we patch the source module's attributes."""
    def _install(connection=None, latest=None, recent=None):
        import packages.integrations.youtube.client as real_yt
        fake = _FakeYT(connection=connection, latest=latest, recent=recent)
        monkeypatch.setattr(real_yt, "get_connection", fake.get_connection)
        monkeypatch.setattr(real_yt, "get_fresh_access_token", fake.get_fresh_access_token)
        monkeypatch.setattr(real_yt, "get_recent_uploads", fake.get_recent_uploads)
        return fake
    return _install


@pytest.fixture
def stub_dispatch(monkeypatch):
    """Replace _dispatch_publisher with a recorder so tests assert on whether
    (and with what) the Publisher flow would fire — keeps the orchestrator and
    its LLM/graph machinery out of these unit tests."""
    calls = []

    async def _fake(supabase, org_id, *, video_id, video_title):
        calls.append({"org_id": org_id, "video_id": video_id, "video_title": video_title})

    monkeypatch.setattr(scheduler, "_dispatch_publisher", _fake)
    return calls


@pytest.fixture
def stub_content_dispatch(monkeypatch):
    """Recorder for the Content Agent dispatch — same rationale as
    stub_dispatch. Content dispatch only fires when the org's `agents` row
    for slug `content` is active, so tests exercise the gate by canning (or
    omitting) that row on the supabase mock."""
    calls = []

    async def _fake(supabase, org_id, *, video_id, video_title, published_at=None):
        calls.append({
            "org_id": org_id,
            "video_id": video_id,
            "video_title": video_title,
            "published_at": published_at,
        })

    monkeypatch.setattr(scheduler, "_dispatch_content", _fake)
    return calls


# ── Poller behaviour ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_org_noop_without_connection(patch_yt, stub_dispatch, mock_supabase):
    """No YouTube integration for the org → poller does nothing, fires no
    Publisher dispatch, and writes no poll state."""
    patch_yt(connection=None)
    await scheduler._poll_org(mock_supabase, "org-1")

    assert stub_dispatch == []
    # No upsert to youtube_poll_state was attempted.
    assert "_upserts" not in mock_supabase._canned


@pytest.mark.asyncio
async def test_poll_org_first_poll_records_head_no_dispatch(
    patch_yt, stub_dispatch, mock_supabase
):
    """First-ever poll of a connected channel records the current head but
    does NOT fire Publisher (avoids packaging a back-catalog video on boot)."""
    patch_yt(
        connection={
            "metadata": {"channel_id": "chan1", "uploads_playlist_id": "UU_chan1"},
            "access_token": "x",
            "token_expires_at": None,
        },
        latest={"video_id": "vidA", "video_title": "Hello", "published_at": "now"},
    )
    # No prior poll state row in the mock → last_seen is None → first poll.
    await scheduler._poll_org(mock_supabase, "org-1")

    assert stub_dispatch == []  # did NOT dispatch
    upserts = mock_supabase._canned.get("_upserts", [])
    assert len(upserts) == 1
    table, payload = upserts[0]
    assert table == "youtube_poll_state"
    assert payload["last_seen_video_id"] == "vidA"  # head recorded


@pytest.mark.asyncio
async def test_poll_org_new_upload_triggers_publisher(
    patch_yt, stub_dispatch, mock_supabase_factory
):
    """A latest upload id different from last_seen fires the Publisher
    create_package dispatch and advances last_seen_video_id."""
    sb = mock_supabase_factory({
        "youtube_poll_state": [
            {"org_id": "org-1", "channel_id": "chan1", "last_seen_video_id": "vidOLD"}
        ],
    })
    patch_yt(
        connection={
            "metadata": {"channel_id": "chan1", "uploads_playlist_id": "UU_chan1"},
            "access_token": "x",
            "token_expires_at": None,
        },
        latest={"video_id": "vidNEW", "video_title": "Fresh Upload", "published_at": "now"},
    )

    await scheduler._poll_org(sb, "org-1")

    # Publisher dispatch fired for the new video.
    assert stub_dispatch == [
        {"org_id": "org-1", "video_id": "vidNEW", "video_title": "Fresh Upload"}
    ]
    # last_seen advanced to the new head.
    upserts = sb._canned.get("_upserts", [])
    assert any(
        t == "youtube_poll_state" and p["last_seen_video_id"] == "vidNEW"
        for t, p in upserts
    )


@pytest.mark.asyncio
async def test_poll_org_unchanged_head_no_dispatch(
    patch_yt, stub_dispatch, mock_supabase_factory
):
    """Latest upload equals last_seen → no dispatch, just a polled-at touch."""
    sb = mock_supabase_factory({
        "youtube_poll_state": [
            {"org_id": "org-1", "channel_id": "chan1", "last_seen_video_id": "vidSAME"}
        ],
    })
    patch_yt(
        connection={
            "metadata": {"channel_id": "chan1", "uploads_playlist_id": "UU_chan1"},
            "access_token": "x",
            "token_expires_at": None,
        },
        latest={"video_id": "vidSAME", "video_title": "Same", "published_at": "now"},
    )

    await scheduler._poll_org(sb, "org-1")
    assert stub_dispatch == []


@pytest.mark.asyncio
async def test_poll_org_isolates_youtube_error(
    patch_yt, stub_dispatch, mock_supabase, monkeypatch
):
    """A YouTube API failure is recorded to poll state and does not raise —
    one org failing must not abort the sweep."""
    import packages.integrations.youtube.client as real_yt

    patch_yt(
        connection={
            "metadata": {"channel_id": "chan1", "uploads_playlist_id": "UU_chan1"},
        },
    )

    async def _boom(*a, **k):
        raise RuntimeError("403 quota exceeded")

    monkeypatch.setattr(real_yt, "get_recent_uploads", _boom)

    # Should not raise.
    await scheduler._poll_org(mock_supabase, "org-1")
    assert stub_dispatch == []
    upserts = mock_supabase._canned.get("_upserts", [])
    assert len(upserts) == 1
    _, payload = upserts[0]
    assert "403" in (payload["last_error"] or "")


# ── uploads_since: the list-diff core ───────────────────────────────────────

def _u(vid: str) -> dict:
    return {"video_id": vid, "video_title": f"title-{vid}", "published_at": "now"}


@pytest.mark.parametrize(
    "last_seen, recent_ids, expected_ids",
    [
        (None, ["v3", "v2", "v1"], []),          # first poll → record head only
        ("v3", [], []),                            # empty page → nothing
        ("v3", ["v3", "v2", "v1"], []),           # unchanged head → nothing
        ("v2", ["v3", "v2", "v1"], ["v3"]),       # one new → just it
        ("v1", ["v4", "v3", "v2", "v1"], ["v2", "v3", "v4"]),  # several new → oldest-first
        ("gone", ["v3", "v2", "v1"], ["v1", "v2", "v3"]),      # last_seen absent → whole page
    ],
)
def test_uploads_since(last_seen, recent_ids, expected_ids):
    recent = [_u(v) for v in recent_ids]
    got = [i["video_id"] for i in scheduler.uploads_since(last_seen, recent)]
    assert got == expected_ids


def test_uploads_since_caps_blast_to_newest():
    """last_seen missing from a big page → cap keeps the NEWEST max_dispatch
    uploads (older ones are stale), still returned oldest-first."""
    recent = [_u(f"v{i}") for i in range(9, 0, -1)]  # v9 (newest) … v1
    got = [i["video_id"] for i in scheduler.uploads_since("gone", recent, max_dispatch=3)]
    assert got == ["v7", "v8", "v9"]


# ── Multi-upload sweeps + the Content Agent gate ────────────────────────────

_CONN = {
    "metadata": {"channel_id": "chan1", "uploads_playlist_id": "UU_chan1"},
    "access_token": "x",
    "token_expires_at": None,
}


@pytest.mark.asyncio
async def test_poll_org_multiple_new_uploads_dispatch_oldest_first(
    patch_yt, stub_dispatch, stub_content_dispatch, mock_supabase_factory
):
    """Two uploads landed inside one poll interval → BOTH dispatch, oldest
    first, and last_seen advances to the newest head. (The old head-only diff
    would have silently skipped the older upload.)"""
    sb = mock_supabase_factory({
        "youtube_poll_state": [
            {"org_id": "org-1", "channel_id": "chan1", "last_seen_video_id": "v1"}
        ],
    })
    patch_yt(connection=_CONN, recent=[_u("v3"), _u("v2"), _u("v1")])

    await scheduler._poll_org(sb, "org-1")

    assert [c["video_id"] for c in stub_dispatch] == ["v2", "v3"]
    assert stub_content_dispatch == []  # no active content agent row → gated off
    upserts = sb._canned.get("_upserts", [])
    assert any(
        t == "youtube_poll_state" and p["last_seen_video_id"] == "v3"
        for t, p in upserts
    )


@pytest.mark.asyncio
async def test_poll_org_dispatches_content_agent_when_active(
    patch_yt, stub_dispatch, stub_content_dispatch, mock_supabase_factory
):
    """An active `agents` row for slug `content` turns on the second dispatch
    target: every new upload fires Publisher AND the Content Agent."""
    sb = mock_supabase_factory({
        "youtube_poll_state": [
            {"org_id": "org-1", "channel_id": "chan1", "last_seen_video_id": "v1"}
        ],
        "agents": [{"slug": "content", "active": True}],
    })
    patch_yt(connection=_CONN, recent=[_u("v2"), _u("v1")])

    await scheduler._poll_org(sb, "org-1")

    assert [c["video_id"] for c in stub_dispatch] == ["v2"]
    assert [c["video_id"] for c in stub_content_dispatch] == ["v2"]
    # published_at rides along — it anchors Riverside recording matching.
    assert stub_content_dispatch[0]["published_at"] == "now"


@pytest.mark.asyncio
async def test_poll_org_midbatch_failure_resumes_from_failed_video(
    patch_yt, stub_content_dispatch, mock_supabase_factory, monkeypatch
):
    """Dispatch fails on the SECOND of two new uploads → last_seen stays on
    the first (successfully dispatched) video, so the next sweep retries
    exactly the failed one — no re-fire of v2, no silent skip of v3."""
    sb = mock_supabase_factory({
        "youtube_poll_state": [
            {"org_id": "org-1", "channel_id": "chan1", "last_seen_video_id": "v1"}
        ],
    })
    patch_yt(connection=_CONN, recent=[_u("v3"), _u("v2"), _u("v1")])

    dispatched = []

    async def _flaky(supabase, org_id, *, video_id, video_title):
        if video_id == "v3":
            raise RuntimeError("orchestrator hiccup")
        dispatched.append(video_id)

    monkeypatch.setattr(scheduler, "_dispatch_publisher", _flaky)

    await scheduler._poll_org(sb, "org-1")

    assert dispatched == ["v2"]
    upserts = sb._canned.get("_upserts", [])
    assert len(upserts) == 1
    _, payload = upserts[0]
    assert payload["last_seen_video_id"] == "v2"  # NOT v3, NOT v1
    assert "dispatch failed" in (payload["last_error"] or "")


# ── Content pipeline task plumbing ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_content_skips_when_inflight(mock_supabase, monkeypatch):
    """A pipeline already running for (org, video) → duplicate dispatch is a
    no-op: no ledger upsert, no second task forked against the same row."""
    spawned = []

    async def _fake_run(*a, **k):
        spawned.append(k)

    # Patch where the function actually LIVES (content_dispatch) — the
    # scheduler name is a re-export and _dispatch_content resolves the
    # runner from its own module globals.
    from app.services import content_dispatch

    monkeypatch.setattr(content_dispatch, "_run_content_pipeline", _fake_run)
    key = ("org-1", "vidX")
    scheduler._content_inflight.add(key)
    try:
        await scheduler._dispatch_content(
            mock_supabase, "org-1", video_id="vidX", video_title="t", published_at=None
        )
        assert "_upserts" not in mock_supabase._canned
        assert spawned == []
    finally:
        scheduler._content_inflight.discard(key)


def test_mark_failed_if_stuck_flips_nonterminal(mock_supabase_factory):
    """Run ended with the ledger still 'processing' → marked failed with the
    reason, so the dashboard never shows a silently-stuck pipeline."""
    sb = mock_supabase_factory({
        "content_pipelines": [{"org_id": "org-1", "video_id": "v1", "status": "processing"}],
    })
    scheduler._mark_failed_if_stuck(sb, "org-1", "v1", reason="run died")
    updates = sb._canned.get("_updates", [])
    assert updates and updates[0][0] == "content_pipelines"
    assert updates[0][1]["status"] == "failed"
    assert updates[0][1]["error"] == "run died"


def test_mark_failed_if_stuck_never_downgrades_reviewable(mock_supabase_factory):
    """A row that reached ready_for_review keeps its assets even if the run's
    tail end errored — the check must not regress completed work."""
    sb = mock_supabase_factory({
        "content_pipelines": [{"org_id": "org-1", "video_id": "v1", "status": "ready_for_review"}],
    })
    scheduler._mark_failed_if_stuck(sb, "org-1", "v1", reason="late error")
    assert sb._canned.get("_updates", []) == []


# ── App import stays hermetic ───────────────────────────────────────────────

def test_importing_app_does_not_start_loop():
    """Importing the FastAPI app (and constructing it) must not spawn the poll
    loop. The loop is only created inside the lifespan via start_scheduler,
    and start_scheduler is a no-op while scheduler_enabled is False (default)."""
    import app.main  # noqa: F401 — import side-effects are what we're checking

    assert scheduler._task is None


def test_start_scheduler_noop_when_disabled():
    """start_scheduler creates no task while the feature flag is off."""
    from app.config import get_settings

    assert get_settings().scheduler_enabled is False
    scheduler.start_scheduler()
    assert scheduler._task is None
