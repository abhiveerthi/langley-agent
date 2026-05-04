"""
Slack-side metadata for UI pickers (notably the invite-form channel
dropdown on /app/settings/team).

  GET /api/slack/channels   list channels the org's bot can post to

Live `conversations.list` call wrapped in a 5-minute in-memory TTL cache
keyed by org_id. Volume is tiny (one fetch per org per page-load every
~5 minutes) so a process-local dict is fine; if multi-replica caching
becomes an issue, lift to Redis.
"""
from __future__ import annotations

import time
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase
from packages.integrations.slack import client as slack_client

router = APIRouter(tags=["slack_meta"])

_CACHE_TTL_SECONDS = 5 * 60
_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = Lock()


class SlackChannel(BaseModel):
    id: str
    name: str
    is_private: bool
    is_member: bool


class SlackChannelsResponse(BaseModel):
    installed: bool
    channels: list[SlackChannel]


def _cached(org_id: str) -> list[dict] | None:
    with _cache_lock:
        entry = _cache.get(org_id)
        if not entry:
            return None
        ts, channels = entry
        if time.time() - ts > _CACHE_TTL_SECONDS:
            _cache.pop(org_id, None)
            return None
        return channels


def _set_cache(org_id: str, channels: list[dict]) -> None:
    with _cache_lock:
        _cache[org_id] = (time.time(), channels)


@router.get("/slack/channels", response_model=SlackChannelsResponse)
async def list_slack_channels(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    conn = slack_client.get_connection(supabase, user.org_id)
    if not conn:
        return SlackChannelsResponse(installed=False, channels=[])

    access_token = conn.get("access_token")
    if not access_token:
        return SlackChannelsResponse(installed=False, channels=[])

    cached = _cached(user.org_id)
    if cached is not None:
        return SlackChannelsResponse(
            installed=True,
            channels=[SlackChannel(**c) for c in cached if c.get("is_member")],
        )

    try:
        channels = await slack_client.list_conversations(access_token)
    except Exception as e:
        # Don't 500 the whole team page if Slack is rate-limited; return
        # an empty list so the UI can fall back to "Slack listing
        # unavailable, try again in a minute".
        raise HTTPException(
            status_code=503,
            detail=f"Slack listing temporarily unavailable: {e}",
        )

    _set_cache(user.org_id, channels)
    member_channels = [c for c in channels if c.get("is_member")]
    return SlackChannelsResponse(
        installed=True,
        channels=[SlackChannel(**c) for c in member_channels],
    )
