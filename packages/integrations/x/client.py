from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx
from supabase import Client

from packages.integrations.x.oauth import (
    OAuthTokens,
    refresh_access_token,
)

PROVIDER = "twitter"
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
    user: dict,
) -> dict:
    row = {
        "org_id": org_id,
        "provider": PROVIDER,
        "status": "active",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_expires_at": _expires_at(tokens.expires_in),
        "scopes": tokens.scope.split() if tokens.scope else [],
        "metadata": user,
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
    client_secret: str | None = None,
) -> str:
    conn = get_connection(supabase, org_id)
    if not conn:
        raise RuntimeError("X is not connected for this org")

    expires_at_iso = conn.get("token_expires_at")
    expired = True
    if expires_at_iso:
        expires_dt = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
        expired = expires_dt.timestamp() - time.time() < REFRESH_SKEW_SECONDS

    if not expired:
        return conn["access_token"]

    if not conn.get("refresh_token"):
        raise RuntimeError(
            "No refresh token on file; reconnect X (the offline.access scope is required)"
        )

    tokens = await refresh_access_token(
        conn["refresh_token"], client_id, client_secret=client_secret
    )
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


async def mark_connection_error(supabase: Client, org_id: str, error: str) -> None:
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


async def post_tweet(access_token: str, text: str) -> dict:
    """POST /2/tweets. Returns {id, text} on success.

    Raises RuntimeError with a friendly message on common failure modes
    (free-tier write block, rate limit, expired token).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.x.com/2/tweets",
            json={"text": text},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code == 201:
        data = resp.json().get("data") or {}
        return {"id": data.get("id"), "text": data.get("text") or text}

    body = resp.text
    if resp.status_code == 403:
        # Most common cause: free tier doesn't allow POST /2/tweets.
        raise RuntimeError(
            "X rejected the post (403). Writes require the Basic ($200/mo) tier or "
            f"higher, or the connected app may be missing tweet.write scope. Body: {body}"
        )
    if resp.status_code == 429:
        retry_after = resp.headers.get("x-rate-limit-reset") or resp.headers.get("retry-after")
        raise RuntimeError(
            f"X rate limit hit (429). Retry after {retry_after or 'unknown'}: {body}"
        )
    if resp.status_code == 401:
        raise RuntimeError(f"X access token rejected (401). Reconnect X. Body: {body}")
    raise RuntimeError(f"X tweet failed: {resp.status_code} {body}")
