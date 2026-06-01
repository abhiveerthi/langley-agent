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
    `latest` is what get_latest_upload returns. `dispatched` records calls so
    tests can assert the Publisher flow did/didn't fire — without monkeypatching
    the whole orchestrator we instead intercept get_latest_upload + the
    publisher dispatch via the supabase mock's recorded inserts.
    """

    def __init__(self, connection=None, latest=None):
        self.connection = connection
        self.latest = latest
        self.token_calls = 0

    def get_connection(self, supabase, org_id):
        return self.connection

    async def get_fresh_access_token(self, supabase, org_id, cid, csecret):
        self.token_calls += 1
        return "fake-access-token"

    async def get_latest_upload(self, access_token, uploads_playlist_id):
        return self.latest


@pytest.fixture
def patch_yt(monkeypatch):
    """Install a _FakeYT as the scheduler's `yt` module. The scheduler imports
    the client lazily inside _poll_org (`from packages.integrations.youtube
    import client as yt`), so we patch the source module's attributes."""
    def _install(connection=None, latest=None):
        import packages.integrations.youtube.client as real_yt
        fake = _FakeYT(connection=connection, latest=latest)
        monkeypatch.setattr(real_yt, "get_connection", fake.get_connection)
        monkeypatch.setattr(real_yt, "get_fresh_access_token", fake.get_fresh_access_token)
        monkeypatch.setattr(real_yt, "get_latest_upload", fake.get_latest_upload)
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

    monkeypatch.setattr(real_yt, "get_latest_upload", _boom)

    # Should not raise.
    await scheduler._poll_org(mock_supabase, "org-1")
    assert stub_dispatch == []
    upserts = mock_supabase._canned.get("_upserts", [])
    assert len(upserts) == 1
    _, payload = upserts[0]
    assert "403" in (payload["last_error"] or "")


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
