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
