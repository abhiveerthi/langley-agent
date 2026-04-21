from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

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
