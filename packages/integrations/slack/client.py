from __future__ import annotations

from datetime import datetime, timezone

import httpx
from supabase import Client

from packages.integrations.slack.oauth import OAuthInstall

PROVIDER = "slack"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    install: OAuthInstall,
    extra_metadata: dict | None = None,
) -> dict:
    metadata = {
        "team_id": install.team_id,
        "team_name": install.team_name,
        "bot_user_id": install.bot_user_id,
        "app_id": install.app_id,
        "authed_user_id": install.authed_user_id,
        "installed_at": _now_iso(),
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    row = {
        "org_id": org_id,
        "provider": PROVIDER,
        "status": "active",
        "access_token": install.access_token,
        # Slack doesn't issue a refresh token by default. Token rotation is
        # opt-in; if/when we enable it, swap in expiry handling.
        "refresh_token": install.authed_user_token,
        "token_expires_at": None,
        "scopes": _split_scopes(install.scope),
        "metadata": metadata,
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


def mark_connection_error(supabase: Client, org_id: str, error: str) -> None:
    conn = get_connection(supabase, org_id)
    metadata = (conn or {}).get("metadata") or {}
    metadata["last_error"] = error
    (
        supabase.table("integrations")
        .update({"status": "error", "metadata": metadata})
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )


def _split_scopes(scope: str) -> list[str]:
    """Slack returns scopes comma-separated. Older endpoints used spaces — handle both."""
    if not scope:
        return []
    raw = scope.replace(" ", ",")
    return [s for s in (p.strip() for p in raw.split(",")) if s]


# ── Slack Web API helpers ──────────────────────────────────────────────────

SLACK_API_BASE = "https://slack.com/api"


async def _slack_post(access_token: str, method: str, payload: dict) -> dict:
    """POST to Slack Web API with bearer auth + JSON body, raise on failure.

    Slack's 200-with-error pattern (HTTP 200, `ok: false`) gets surfaced as a
    RuntimeError carrying the Slack error code so callers can give actionable
    messages (e.g. `not_in_channel`, `name_taken`).
    """
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(
            f"{SLACK_API_BASE}/{method}",
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code >= 400:
        raise RuntimeError(f"Slack {method} HTTP {resp.status_code}: {resp.text}")
    if not body.get("ok"):
        raise RuntimeError(f"Slack {method} rejected: {body.get('error') or body}")
    return body


async def _slack_get(access_token: str, method: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.get(
            f"{SLACK_API_BASE}/{method}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code >= 400:
        raise RuntimeError(f"Slack {method} HTTP {resp.status_code}: {resp.text}")
    if not body.get("ok"):
        raise RuntimeError(f"Slack {method} rejected: {body.get('error') or body}")
    return body


# ── Posting ────────────────────────────────────────────────────────────────

async def post_message_in_thread(
    access_token: str,
    channel: str,
    text: str,
    *,
    thread_ts: str | None = None,
    username: str | None = None,
    icon_emoji: str | None = None,
    blocks: list[dict] | None = None,
) -> dict:
    """Post via chat.postMessage. If thread_ts is set, replies into that
    Slack thread; otherwise posts at the top level. Returns {ts, channel}.

    `username` + `icon_emoji` let one bot user post under per-agent
    display names. They require the `chat:write.customize` scope on the
    install — without it, Slack rejects the post with `not_allowed`. The
    caller (slack_runner / oauth callback) gates these via
    `oauth.persona_for(agent_slug, scopes)` so older installs don't break.

    `blocks` is for Block Kit messages (approval cards, etc). When
    blocks are present, `text` is used as the notification fallback.
    """
    payload: dict = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji
    if blocks:
        payload["blocks"] = blocks
    body = await _slack_post(access_token, "chat.postMessage", payload)
    return {"ts": body.get("ts"), "channel": body.get("channel")}


async def update_message(
    access_token: str,
    channel: str,
    ts: str,
    text: str,
    *,
    blocks: list[dict] | None = None,
) -> dict:
    """chat.update an existing message in place. Used to flip an approval
    card to its post-resolution form (✅ Approved / ❌ Rejected)."""
    payload: dict = {"channel": channel, "ts": ts, "text": text}
    if blocks:
        payload["blocks"] = blocks
    body = await _slack_post(access_token, "chat.update", payload)
    return {"ts": body.get("ts"), "channel": body.get("channel")}


async def open_modal(access_token: str, trigger_id: str, view: dict) -> dict:
    """Open a Slack modal via views.open. `trigger_id` is short-lived
    (≈3 s after the user clicks); call this synchronously from the
    interactive handler before doing any other work."""
    body = await _slack_post(
        access_token, "views.open", {"trigger_id": trigger_id, "view": view}
    )
    return body.get("view") or {}


async def get_message(
    access_token: str, channel: str, ts: str
) -> dict | None:
    """Fetch a single posted message by `ts` via conversations.history with
    a tight `oldest`/`latest` window. Used to grab the original blocks of an
    approval card so `chat.update` can render the resolved form on top of
    the same content. Returns None if not found (rare — mostly when ts has
    drifted off due to retention)."""
    body = await _slack_get(
        access_token,
        "conversations.history",
        {
            "channel": channel,
            "oldest": ts,
            "latest": ts,
            "inclusive": "true",
            "limit": 1,
        },
    )
    msgs = body.get("messages") or []
    return msgs[0] if msgs else None


async def post_message(access_token: str, channel: str, text: str) -> dict:
    """Backwards-compatible top-level post. Prefer post_message_in_thread."""
    return await post_message_in_thread(access_token, channel, text)


# ── Channels ───────────────────────────────────────────────────────────────

async def create_private_channel(
    access_token: str,
    name: str,
    *,
    invite_user_ids: list[str] | None = None,
) -> dict:
    """Create a private channel via conversations.create. If invite_user_ids
    is non-empty, invites them (the bot is auto-added as the creator).

    Returns {channel_id, name}. If a channel with `name` already exists in
    the workspace, Slack returns `name_taken` — caller should handle by
    looking up the existing id via conversations.list.
    """
    body = await _slack_post(
        access_token,
        "conversations.create",
        {"name": name, "is_private": True},
    )
    channel = body.get("channel") or {}
    channel_id = channel.get("id")
    if invite_user_ids:
        # conversations.invite takes a comma-separated list of user ids.
        await _slack_post(
            access_token,
            "conversations.invite",
            {"channel": channel_id, "users": ",".join(invite_user_ids)},
        )
    return {"channel_id": channel_id, "name": channel.get("name")}


# ── Users ──────────────────────────────────────────────────────────────────

async def lookup_user_email(access_token: str, user_id: str) -> str | None:
    """Fetch a Slack user's email via users.info. Requires users:read.email
    scope. Returns None if the user has no email set or the field is hidden
    by workspace privacy settings."""
    body = await _slack_get(access_token, "users.info", {"user": user_id})
    profile = (body.get("user") or {}).get("profile") or {}
    return profile.get("email") or None
