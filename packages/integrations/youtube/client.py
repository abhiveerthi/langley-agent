from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from supabase import Client

from packages.integrations.youtube.oauth import (
    OAuthTokens,
    refresh_access_token,
)

PROVIDER = "youtube"
REFRESH_SKEW_SECONDS = 120


def _expires_at(expires_in: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()


def get_connection(supabase: Client, org_id: str) -> dict | None:
    resp = (
        supabase.table("integrations")
        .select("*")
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def save_connection(
    supabase: Client,
    org_id: str,
    tokens: OAuthTokens,
    channel: dict,
) -> dict:
    row = {
        "org_id": org_id,
        "provider": PROVIDER,
        "status": "active",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_expires_at": _expires_at(tokens.expires_in),
        "scopes": tokens.scope.split() if tokens.scope else [],
        "metadata": channel,
    }
    resp = (
        supabase.table("integrations")
        .upsert(row, on_conflict="org_id,provider")
        .execute()
    )
    return resp.data[0]


def delete_connection(supabase: Client, org_id: str) -> None:
    (
        supabase.table("integrations")
        .delete()
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )


def get_channel_id(supabase: Client, org_id: str) -> str | None:
    """Return the connected creator's YouTube channel_id, if OAuth is connected.

    Sourced from the row written by the OAuth callback (`save_connection`),
    so it tracks the account the user actually authorized — no separate
    profile config required.
    """
    conn = get_connection(supabase, org_id)
    if not conn:
        return None
    return (conn.get("metadata") or {}).get("channel_id")


async def get_fresh_access_token(
    supabase: Client,
    org_id: str,
    client_id: str,
    client_secret: str,
) -> str:
    conn = get_connection(supabase, org_id)
    if not conn:
        raise RuntimeError("YouTube is not connected for this org")

    expires_at_iso = conn.get("token_expires_at")
    expired = True
    if expires_at_iso:
        expires_dt = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
        expired = expires_dt.timestamp() - time.time() < REFRESH_SKEW_SECONDS

    if not expired:
        return conn["access_token"]

    if not conn.get("refresh_token"):
        raise RuntimeError("No refresh token on file; reconnect YouTube")

    tokens = await refresh_access_token(conn["refresh_token"], client_id, client_secret)
    (
        supabase.table("integrations")
        .update(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_expires_at": _expires_at(tokens.expires_in),
                "scopes": tokens.scope.split() if tokens.scope else conn.get("scopes", []),
                "status": "active",
            }
        )
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )
    return tokens.access_token


async def get_recent_uploads(
    access_token: str, uploads_playlist_id: str, *, limit: int = 10
) -> list[dict]:
    """Return the channel's most recent uploads, newest first.

    Same cheap `playlistItems` read as `get_latest_upload` (1 quota unit vs
    search.list's 100) but a full page instead of head-only, so the poller can
    catch EVERY upload since the last sweep — a channel posting a short, two
    longforms, and a live VOD daily can land 2+ uploads inside one poll
    interval, and a head-only diff would silently skip the older ones.

    Each item has `video_id`, `video_title`, `published_at` (the
    `get_latest_upload` shape). Raises on transport/API errors so the caller
    can record + isolate the failure per-org.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": max(1, min(int(limit), 50)),
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Recent-uploads lookup failed: {resp.status_code} {resp.text}"
        )
    out: list[dict] = []
    for item in resp.json().get("items") or []:
        snippet = item.get("snippet") or {}
        content = item.get("contentDetails") or {}
        out.append({
            "video_id": content.get("videoId") or snippet.get("resourceId", {}).get("videoId"),
            "video_title": snippet.get("title"),
            "published_at": content.get("videoPublishedAt") or snippet.get("publishedAt"),
        })
    return out


async def get_latest_upload(
    access_token: str, uploads_playlist_id: str
) -> dict | None:
    """Return the most-recent upload on a channel's uploads playlist.

    The "uploads" playlist (id from `fetch_channel_info`'s
    `uploads_playlist_id`) is auto-maintained by YouTube and ordered
    newest-first, so a single `playlistItems` page of size 1 is the cheapest
    way to detect a new upload — no `search.list` quota hit (100 units) when
    a `playlistItems.list` (1 unit) does the job.

    Returns a dict with `video_id`, `video_title`, and `published_at`, or
    None when the playlist is empty (brand-new channel). Raises on transport
    / API errors so the caller can record + isolate the failure per-org.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": 1,
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Latest-upload lookup failed: {resp.status_code} {resp.text}"
        )
    items = resp.json().get("items") or []
    if not items:
        return None
    item = items[0]
    snippet = item.get("snippet") or {}
    content = item.get("contentDetails") or {}
    return {
        "video_id": content.get("videoId") or snippet.get("resourceId", {}).get("videoId"),
        "video_title": snippet.get("title"),
        "published_at": content.get("videoPublishedAt") or snippet.get("publishedAt"),
    }


def _parse_iso8601_duration(value: str | None) -> int:
    """PT1H2M3S → seconds. 0 on anything unparseable (caller treats unknown
    duration as 'route conservatively')."""
    import re as _re

    if not value:
        return 0
    m = _re.fullmatch(
        r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value.strip()
    )
    if not m:
        return 0
    d, h, mnt, s = (int(g) if g else 0 for g in m.groups())
    return d * 86400 + h * 3600 + mnt * 60 + s


async def get_video_details(access_token: str, video_id: str) -> dict | None:
    """Duration + live-stream flag for one video — the Content Agent's
    routing inputs (podcast lane iff live and long enough; Shorts skip
    clipping). One videos.list call (1 quota unit).

    Returns {"duration_seconds": int, "is_live": bool, "title": str} or
    None when the video isn't visible. `is_live` is true for anything that
    was (or is) a live broadcast — liveStreamingDetails is present on live
    VODs after the stream ends, which is exactly the nightly-stream case.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "contentDetails,liveStreamingDetails,snippet",
                "id": video_id,
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Video details lookup failed: {resp.status_code} {resp.text[:200]}"
        )
    items = resp.json().get("items") or []
    if not items:
        return None
    item = items[0]
    duration = _parse_iso8601_duration(
        (item.get("contentDetails") or {}).get("duration")
    )
    return {
        "duration_seconds": duration,
        "is_live": "liveStreamingDetails" in item,
        "title": (item.get("snippet") or {}).get("title") or "",
    }


async def upload_video(
    access_token: str,
    *,
    video_bytes: bytes,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy_status: str = "public",
) -> dict:
    """Upload a video (Content Agent: approved Shorts clips) via the
    resumable protocol: initiate with metadata, then PUT the bytes to the
    session URL Google returns. Requires the youtube.upload scope (already
    in YOUTUBE_SCOPES; connections created before it shipped need a
    reconnect — surfaced by the 403 message below).

    Returns {"video_id", "url"}. Raises RuntimeError with an actionable
    message on failure; callers record it per-asset and move on.
    """
    metadata = {
        "snippet": {
            "title": (title or "Untitled")[:100],
            "description": description[:4900],
            "tags": (tags or [])[:30],
            "categoryId": "22",  # People & Blogs — safe default
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    async with httpx.AsyncClient(timeout=600) as client:
        init = await client.post(
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=metadata,
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(len(video_bytes)),
            },
        )
        if init.status_code >= 400:
            hint = (
                " (missing youtube.upload scope? Reconnect YouTube to grant it)"
                if init.status_code == 403
                else ""
            )
            raise RuntimeError(
                f"YouTube upload init failed: {init.status_code}{hint} {init.text[:300]}"
            )
        session_url = init.headers.get("location")
        if not session_url:
            raise RuntimeError("YouTube upload init returned no session URL")

        put = await client.put(
            session_url,
            content=video_bytes,
            headers={"Content-Type": "video/mp4"},
        )
    if put.status_code >= 400:
        raise RuntimeError(f"YouTube upload failed: {put.status_code} {put.text[:300]}")
    video_id = (put.json() or {}).get("id")
    if not video_id:
        raise RuntimeError(f"YouTube upload returned no video id: {put.text[:200]}")
    return {"video_id": video_id, "url": f"https://www.youtube.com/shorts/{video_id}"}


async def mark_connection_error(
    supabase: Client, org_id: str, error: str
) -> None:
    (
        supabase.table("integrations")
        .update({"status": "error", "metadata": {"last_error": error}})
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )
