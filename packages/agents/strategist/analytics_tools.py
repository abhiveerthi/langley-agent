"""
Strategist's OAuth-backed YouTube Analytics tools.

Distinct from `tools.py` which uses the public Data API (likes, view counts,
comment counts — anything any viewer can see). These tools hit the YouTube
**Analytics** API and return the creator-private signals that actually drive
strategy decisions: watch time, average view duration, retention, and traffic
sources (browse / search / suggested / external).

Why a separate module: the Analytics API uses a different base URL, requires
OAuth (not an API key), and only works for the connected channel via
`ids=channel==MINE`. Mixing it into tools.py would obscure the "this needs
OAuth, that doesn't" distinction. The Strategist's `get_strategist_tools()`
exports them alongside the public-data tools and the LLM picks which to use
based on what the user's asking.

Auth pattern mirrors `community_manager.tools.reply_to_comment` — read
`current_org_id` + `current_supabase` from ContextVars, fetch a fresh access
token via the existing OAuth helper, hit the API, surface clean error
strings if anything's misconfigured rather than raising.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from langchain_core.tools import tool

from packages.agents.core.clients import youtube_api_get
from packages.integrations.context import current_org_id, current_supabase
from packages.integrations.youtube.client import get_fresh_access_token


_ANALYTICS_BASE = "https://youtubeanalytics.googleapis.com/v2/reports"

# Standard metric bundles. Exposed as module-level so tests + future tools
# can reference the same set.
_OVERVIEW_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,"
    "averageViewPercentage,subscribersGained,subscribersLost"
)
_PER_VIDEO_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage"
)


# ── Date helpers ──────────────────────────────────────────────────────────
def _date_window(days: int) -> tuple[str, str]:
    """Return (startDate, endDate) ISO strings for the trailing N-day window."""
    days = max(1, min(days, 365))
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


# ── OAuth-backed Analytics fetcher (private to this module) ──────────────
async def _analytics_get(params: dict) -> dict | str:
    """Hit YouTube Analytics with the connected creator's OAuth token.

    Returns the parsed JSON response on success, or a user-readable error
    string on any failure. Tools surface the string verbatim — keeps the
    LLM-visible failure mode consistent ("Cannot fetch analytics: …")
    rather than a stack trace.
    """
    org_id = current_org_id.get()
    supabase = current_supabase.get()
    if not org_id or supabase is None:
        return ("Cannot fetch analytics: no org context (running locally without "
                "auth). Connect YouTube on a real org to use this tool.")

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return "Cannot fetch analytics: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not configured."

    try:
        access_token = await get_fresh_access_token(
            supabase, org_id, client_id, client_secret
        )
    except Exception as e:
        return f"Cannot fetch analytics: YouTube not connected for this org ({e})."

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                _ANALYTICS_BASE,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:200]
        return f"YouTube Analytics rejected the request ({e.response.status_code}): {body}"
    except Exception as e:
        return f"Error fetching analytics: {e}"


def _rows_as_dicts(payload: dict) -> list[dict[str, Any]]:
    """Reshape the Analytics columnar response into row dicts keyed by header
    name. Saves callers from indexing rows by position."""
    headers = [h["name"] for h in payload.get("columnHeaders", [])]
    return [dict(zip(headers, row)) for row in payload.get("rows", [])]


def _fmt_minutes(minutes: float) -> str:
    """Format minutes into "Hh Mm" — easier to read than raw decimals."""
    total = int(round(minutes))
    h, m = divmod(total, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def _fmt_seconds(seconds: float) -> str:
    """Format seconds into "Mm SSs" — matches creator mental model for AVD."""
    total = int(round(seconds))
    m, s = divmod(total, 60)
    return f"{m}m {s:02d}s"


# ── Tool 1: channel-level overview ────────────────────────────────────────
@tool
async def get_channel_analytics_overview(days: int = 28) -> str:
    """Get the connected channel's high-level analytics for the trailing window.

    Returns total views, watch time, average view duration, average view %,
    and net subscriber change — the OAuth-only metrics the public Data API
    can't see. Use this for "how is the channel doing overall right now"
    questions and for grounding the weekly brief's headline.

    Args:
        days: Trailing window in days (default 28, max 365).
    """
    start, end = _date_window(days)
    payload = await _analytics_get({
        "ids": "channel==MINE",
        "startDate": start,
        "endDate": end,
        "metrics": _OVERVIEW_METRICS,
    })
    if isinstance(payload, str):
        return payload  # error string

    rows = _rows_as_dicts(payload)
    if not rows:
        return f"No analytics data for the last {days} days (channel may be new or have no public videos)."

    r = rows[0]
    views = int(r.get("views", 0))
    watch_min = float(r.get("estimatedMinutesWatched", 0))
    avd_sec = float(r.get("averageViewDuration", 0))
    avp = float(r.get("averageViewPercentage", 0))
    subs_gained = int(r.get("subscribersGained", 0))
    subs_lost = int(r.get("subscribersLost", 0))
    net_subs = subs_gained - subs_lost

    return (
        f"# Channel Analytics — last {days} days ({start} to {end})\n\n"
        f"- Views: {views:,}\n"
        f"- Watch time: {_fmt_minutes(watch_min)}\n"
        f"- Avg view duration: {_fmt_seconds(avd_sec)}\n"
        f"- Avg % watched: {avp:.1f}%\n"
        f"- Net subscribers: {net_subs:+,}  ({subs_gained:,} gained / {subs_lost:,} lost)\n"
    )


# ── Tool 2: per-video analytics for recent uploads ────────────────────────
@tool
async def get_video_analytics_performance(limit: int = 10, days: int = 28) -> str:
    """Per-video Analytics for the connected channel's top recent videos.

    Returns watch time, average view duration, and average view % for each
    video — the signals that distinguish "this hook worked" from "this title
    pulled clicks but lost the audience by 30 seconds." Use this when a
    weekly brief needs to cite which recent uploads kept attention vs. which
    didn't.

    Args:
        limit: Number of top videos to return (default 10, max 25).
        days: Trailing window in days (default 28).
    """
    limit = max(1, min(limit, 25))
    start, end = _date_window(days)

    payload = await _analytics_get({
        "ids": "channel==MINE",
        "startDate": start,
        "endDate": end,
        "metrics": _PER_VIDEO_METRICS,
        "dimensions": "video",
        "sort": "-views",
        "maxResults": limit,
    })
    if isinstance(payload, str):
        return payload

    rows = _rows_as_dicts(payload)
    if not rows:
        return f"No per-video analytics for the last {days} days."

    # Analytics API gives us video IDs but not titles — fetch titles via the
    # public Data API (no OAuth needed for titles) and join.
    video_ids = [r["video"] for r in rows if r.get("video")]
    titles: dict[str, str] = {}
    if video_ids:
        try:
            data = await youtube_api_get("videos", {
                "part": "snippet",
                "id": ",".join(video_ids),
            })
            for item in data.get("items", []):
                titles[item["id"]] = item["snippet"]["title"]
        except Exception:
            pass  # best-effort — fall back to bare video IDs

    output = f"# Per-Video Analytics — last {days} days (top {len(rows)})\n\n"
    for r in rows:
        vid = r.get("video", "?")
        title = titles.get(vid, f"(video {vid})")
        views = int(r.get("views", 0))
        avd = float(r.get("averageViewDuration", 0))
        avp = float(r.get("averageViewPercentage", 0))
        watch_min = float(r.get("estimatedMinutesWatched", 0))
        output += f"## {title}\n"
        output += (
            f"- Views: {views:,} | Watch time: {_fmt_minutes(watch_min)} | "
            f"AVD: {_fmt_seconds(avd)} | Avg watched: {avp:.1f}%\n\n"
        )
    return output


# ── Tool 3: discovery / traffic source breakdown ──────────────────────────
@tool
async def get_traffic_sources(days: int = 28) -> str:
    """Discovery breakdown for the connected channel's videos.

    Splits views and watch time by traffic source type — Browse features,
    YouTube search, Suggested videos, External (TikTok/Twitter/etc), Notifications,
    Channel page, Playlists. Tells the Strategist whether recent growth came
    from algorithmic discovery (the algorithm liked the video) vs. existing-
    audience plays (subs notification, channel page, playlists), which is a
    very different signal.

    Args:
        days: Trailing window in days (default 28).
    """
    start, end = _date_window(days)
    payload = await _analytics_get({
        "ids": "channel==MINE",
        "startDate": start,
        "endDate": end,
        "metrics": "views,estimatedMinutesWatched",
        "dimensions": "insightTrafficSourceType",
        "sort": "-views",
    })
    if isinstance(payload, str):
        return payload

    rows = _rows_as_dicts(payload)
    if not rows:
        return f"No traffic source data for the last {days} days."

    total_views = sum(int(r.get("views", 0)) for r in rows) or 1

    output = f"# Traffic Sources — last {days} days\n\n"
    for r in rows:
        source = r.get("insightTrafficSourceType", "UNKNOWN")
        views = int(r.get("views", 0))
        watch_min = float(r.get("estimatedMinutesWatched", 0))
        share = (views / total_views) * 100
        output += (
            f"- **{source}**: {views:,} views ({share:.1f}%), "
            f"{_fmt_minutes(watch_min)} watch time\n"
        )
    return output


def get_strategist_analytics_tools():
    return [
        get_channel_analytics_overview,
        get_video_analytics_performance,
        get_traffic_sources,
    ]
