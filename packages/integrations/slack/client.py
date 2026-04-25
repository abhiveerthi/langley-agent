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


# ── Posting ────────────────────────────────────────────────────────────────

async def post_message(access_token: str, channel: str, text: str) -> dict:
    """Post a message via chat.postMessage. Returns {ts, channel, permalink?}.

    Uses Bearer auth + JSON body — Slack accepts both form and JSON, but JSON
    plays nicer with rich blocks if we add them later.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            json={"channel": channel, "text": text},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code >= 400:
        raise RuntimeError(f"Slack chat.postMessage HTTP {resp.status_code}: {resp.text}")
    if not body.get("ok"):
        # Slack-specific 200-with-error case. Surface the raw error code so the
        # UI can give the user something actionable (e.g. `not_in_channel`).
        raise RuntimeError(f"Slack rejected message: {body.get('error') or body}")
    return {
        "ts": body.get("ts"),
        "channel": body.get("channel"),
        "permalink": body.get("permalink"),
    }
