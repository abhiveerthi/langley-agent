"""
Strategist's OAuth-backed analytics tools — fail-graceful behavior, payload
parsing, and per-tool output formatting.

The tools hit the YouTube Analytics API. Tests mock at the HTTP layer
(`httpx.AsyncClient`) so no live API access is required, and at the
OAuth-token layer so no real Google credentials are needed.

Note: ships ahead of the eval-harness PR's shared `conftest.py` — defines
its own `_reset_contextvars` autouse fixture locally. Easy to port to the
shared fixtures once eval-harness merges.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from packages.agents.strategist.analytics_tools import (
    _date_window,
    _fmt_minutes,
    _fmt_seconds,
    _rows_as_dicts,
    get_channel_analytics_overview,
    get_strategist_analytics_tools,
    get_traffic_sources,
    get_video_analytics_performance,
)
from packages.integrations.context import (
    current_org_id,
    current_supabase,
    current_user_id,
)


# Async test classes are decorated individually with @pytest.mark.asyncio
# below. Until eval-harness merges its `asyncio_mode = "auto"` config, the
# explicit class-level markers keep sync tests warning-free.


@pytest.fixture(autouse=True)
def _reset_contextvars():
    current_org_id.set(None)
    current_user_id.set(None)
    current_supabase.set(None)
    yield


# ── Helpers ───────────────────────────────────────────────────────────────
class _FakeResp:
    """Minimal stand-in for an httpx.Response."""
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status
        self.text = "" if status == 200 else "error body"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(self.status_code, text=self.text),
            )


class _FakeAsyncClient:
    """Async context manager that returns canned responses from .get(...).

    `responses` is a dict mapping URL substring → _FakeResp. The first key
    that matches the requested URL wins."""

    def __init__(self, responses: dict[str, _FakeResp]):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        for key, resp in self._responses.items():
            if key in url:
                return resp
        raise AssertionError(f"Unexpected URL in test: {url}")


def _wire_oauth_and_supabase():
    """Set ContextVars + patch get_fresh_access_token so the tools believe
    they have a connected channel and a fresh access token."""
    current_org_id.set("00000000-0000-0000-0000-000000000001")
    current_supabase.set(object())  # truthy stand-in — never actually called
    return patch(
        "packages.agents.strategist.analytics_tools.get_fresh_access_token",
        AsyncMock(return_value="fake-access-token"),
    )


def _patch_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")


# ── Pure helpers ──────────────────────────────────────────────────────────
class TestDateWindow:
    @pytest.mark.parametrize("days", [1, 7, 28, 90, 365])
    def test_returns_iso_strings_in_range(self, days):
        start, end = _date_window(days)
        assert len(start) == 10 and len(end) == 10
        assert start < end

    def test_clamps_to_365(self):
        start_a, _ = _date_window(365)
        start_b, _ = _date_window(9999)
        assert start_a == start_b

    def test_clamps_to_1(self):
        start_a, end_a = _date_window(1)
        start_b, end_b = _date_window(0)
        assert (start_a, end_a) == (start_b, end_b)


class TestFormatters:
    @pytest.mark.parametrize("minutes, expected", [
        (45, "45m"),
        (60, "1h 0m"),
        (75, "1h 15m"),
        (1500, "25h 0m"),
    ])
    def test_fmt_minutes(self, minutes, expected):
        assert _fmt_minutes(minutes) == expected

    @pytest.mark.parametrize("seconds, expected", [
        (45, "0m 45s"),
        (60, "1m 00s"),
        (272, "4m 32s"),
    ])
    def test_fmt_seconds(self, seconds, expected):
        assert _fmt_seconds(seconds) == expected


class TestRowsAsDicts:
    def test_zips_headers_with_rows(self):
        payload = {
            "columnHeaders": [{"name": "video"}, {"name": "views"}],
            "rows": [["v1", 100], ["v2", 200]],
        }
        assert _rows_as_dicts(payload) == [
            {"video": "v1", "views": 100},
            {"video": "v2", "views": 200},
        ]

    def test_empty_payload(self):
        assert _rows_as_dicts({}) == []
        assert _rows_as_dicts({"rows": [], "columnHeaders": []}) == []


# ── Fail-graceful paths (no OAuth, no creds, OAuth error) ────────────────
@pytest.mark.asyncio
class TestFailGraceful:
    """Every tool should return a clean error STRING (not raise) on any
    misconfiguration. The LLM gets a readable explanation it can quote
    in the user-facing reply."""

    async def test_no_org_context(self):
        # No ContextVars set, no env, no patch — tools should bail early.
        result = await get_channel_analytics_overview.ainvoke({"days": 28})
        assert "no org context" in result.lower() or "Cannot fetch" in result

    async def test_no_google_creds(self, monkeypatch):
        current_org_id.set("00000000-0000-0000-0000-000000000001")
        current_supabase.set(object())
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
        result = await get_channel_analytics_overview.ainvoke({"days": 28})
        assert "GOOGLE_CLIENT_ID" in result

    async def test_oauth_token_fetch_fails(self, monkeypatch):
        _patch_env(monkeypatch)
        current_org_id.set("00000000-0000-0000-0000-000000000001")
        current_supabase.set(object())
        with patch(
            "packages.agents.strategist.analytics_tools.get_fresh_access_token",
            AsyncMock(side_effect=RuntimeError("YouTube is not connected for this org")),
        ):
            result = await get_channel_analytics_overview.ainvoke({"days": 28})
        assert "not connected" in result.lower()


# ── Channel overview happy path ──────────────────────────────────────────
@pytest.mark.asyncio
class TestChannelOverview:
    async def test_renders_canonical_overview(self, monkeypatch):
        _patch_env(monkeypatch)
        payload = {
            "columnHeaders": [
                {"name": "views"}, {"name": "estimatedMinutesWatched"},
                {"name": "averageViewDuration"}, {"name": "averageViewPercentage"},
                {"name": "subscribersGained"}, {"name": "subscribersLost"},
            ],
            "rows": [[152340, 487200, 272, 41.5, 1843, 122]],
        }
        with _wire_oauth_and_supabase():
            with patch("httpx.AsyncClient", return_value=_FakeAsyncClient({
                "youtubeanalytics": _FakeResp(payload),
            })):
                result = await get_channel_analytics_overview.ainvoke({"days": 28})

        assert "152,340" in result
        assert "8120h 0m" in result      # 487200 minutes formatted
        assert "4m 32s" in result        # 272 seconds → AVD
        assert "41.5%" in result
        assert "+1,721" in result        # net subs
        assert "1,843 gained" in result and "122 lost" in result

    async def test_empty_rows_returns_helpful_message(self, monkeypatch):
        _patch_env(monkeypatch)
        with _wire_oauth_and_supabase():
            with patch("httpx.AsyncClient", return_value=_FakeAsyncClient({
                "youtubeanalytics": _FakeResp({"columnHeaders": [], "rows": []}),
            })):
                result = await get_channel_analytics_overview.ainvoke({"days": 28})
        assert "No analytics data" in result


# ── Per-video performance — analytics + Data API title join ───────────────
@pytest.mark.asyncio
class TestPerVideoPerformance:
    async def test_joins_titles_from_data_api(self, monkeypatch):
        _patch_env(monkeypatch)
        analytics_payload = {
            "columnHeaders": [
                {"name": "video"}, {"name": "views"},
                {"name": "estimatedMinutesWatched"},
                {"name": "averageViewDuration"}, {"name": "averageViewPercentage"},
            ],
            "rows": [
                ["vid_a", 50000, 12000, 290, 48.0],
                ["vid_b", 32000, 6400, 200, 35.0],
            ],
        }
        # Mock Data API call — used to fetch titles for the video IDs.
        async def fake_data_api(endpoint, params):
            assert endpoint == "videos"
            return {
                "items": [
                    {"id": "vid_a", "snippet": {"title": "Big Hit Video"}},
                    {"id": "vid_b", "snippet": {"title": "Mid Performer"}},
                ],
            }

        with _wire_oauth_and_supabase():
            with patch(
                "packages.agents.strategist.analytics_tools.youtube_api_get",
                side_effect=fake_data_api,
            ):
                with patch("httpx.AsyncClient", return_value=_FakeAsyncClient({
                    "youtubeanalytics": _FakeResp(analytics_payload),
                })):
                    result = await get_video_analytics_performance.ainvoke({"limit": 10, "days": 28})

        assert "Big Hit Video" in result
        assert "Mid Performer" in result
        assert "50,000" in result      # views
        assert "4m 50s" in result      # 290s AVD on vid_a
        assert "200h 0m" in result     # 12000 min watch time on vid_a

    async def test_data_api_failure_falls_back_to_video_ids(self, monkeypatch):
        """Title-join is best-effort. When the Data API call fails (rate limit,
        missing API key, etc.) we still surface the analytics rows."""
        _patch_env(monkeypatch)
        analytics_payload = {
            "columnHeaders": [
                {"name": "video"}, {"name": "views"},
                {"name": "estimatedMinutesWatched"},
                {"name": "averageViewDuration"}, {"name": "averageViewPercentage"},
            ],
            "rows": [["vid_a", 50000, 12000, 290, 48.0]],
        }

        async def fail_data_api(*_a, **_k):
            raise RuntimeError("API key invalid")

        with _wire_oauth_and_supabase():
            with patch(
                "packages.agents.strategist.analytics_tools.youtube_api_get",
                side_effect=fail_data_api,
            ):
                with patch("httpx.AsyncClient", return_value=_FakeAsyncClient({
                    "youtubeanalytics": _FakeResp(analytics_payload),
                })):
                    result = await get_video_analytics_performance.ainvoke({"limit": 10, "days": 28})

        # No title — falls back to video ID label
        assert "(video vid_a)" in result
        assert "50,000" in result


# ── Traffic sources ───────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestTrafficSources:
    async def test_renders_sources_with_share_percentages(self, monkeypatch):
        _patch_env(monkeypatch)
        payload = {
            "columnHeaders": [
                {"name": "insightTrafficSourceType"},
                {"name": "views"},
                {"name": "estimatedMinutesWatched"},
            ],
            "rows": [
                ["YT_OTHER_PAGE", 60000, 14000],
                ["SUBSCRIBER", 30000, 9000],
                ["YT_SEARCH", 10000, 2000],
            ],
        }
        with _wire_oauth_and_supabase():
            with patch("httpx.AsyncClient", return_value=_FakeAsyncClient({
                "youtubeanalytics": _FakeResp(payload),
            })):
                result = await get_traffic_sources.ainvoke({"days": 28})

        assert "YT_OTHER_PAGE" in result
        assert "60.0%" in result   # 60000/100000
        assert "30.0%" in result
        assert "10.0%" in result
        # And formatted watch time
        assert "233h 20m" in result  # 14000 min


# ── Tools list ────────────────────────────────────────────────────────────
class TestToolsRegistration:
    def test_get_strategist_analytics_tools_returns_three(self):
        tools = get_strategist_analytics_tools()
        names = {t.name for t in tools}
        assert names == {
            "get_channel_analytics_overview",
            "get_video_analytics_performance",
            "get_traffic_sources",
        }

    def test_strategist_agent_includes_analytics_tools(self):
        from packages.agents.strategist.tools import get_strategist_tools
        names = {t.name for t in get_strategist_tools()}
        # Old + new
        assert "get_channel_stats" in names
        assert "get_channel_analytics_overview" in names
        assert "get_traffic_sources" in names
