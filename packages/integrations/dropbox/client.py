from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx
from supabase import Client

from packages.integrations.dropbox.oauth import (
    OAuthTokens,
    refresh_access_token,
)

PROVIDER = "dropbox"
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
    account: dict,
) -> dict:
    metadata = {**account, "uid": tokens.uid, "team_id": tokens.team_id}
    row = {
        "org_id": org_id,
        "provider": PROVIDER,
        "status": "active",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_expires_at": _expires_at(tokens.expires_in),
        "scopes": tokens.scope.split() if tokens.scope else [],
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


async def get_fresh_access_token(
    supabase: Client,
    org_id: str,
    client_id: str,
    client_secret: str,
) -> str:
    conn = get_connection(supabase, org_id)
    if not conn:
        raise RuntimeError("Dropbox is not connected for this org")

    expires_at_iso = conn.get("token_expires_at")
    expired = True
    if expires_at_iso:
        expires_dt = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
        expired = expires_dt.timestamp() - time.time() < REFRESH_SKEW_SECONDS

    if not expired:
        return conn["access_token"]

    if not conn.get("refresh_token"):
        raise RuntimeError(
            "No refresh token on file; reconnect Dropbox (the offline access mode is required)"
        )

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


# ── Helpers used by future agent tools ─────────────────────────────────────

async def list_folder(access_token: str, path: str = "") -> list[dict]:
    """POST /2/files/list_folder. Returns the entries array."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.dropboxapi.com/2/files/list_folder",
            json={"path": path, "limit": 100, "recursive": False},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Dropbox list_folder failed: {resp.status_code} {resp.text}")
    return (resp.json() or {}).get("entries") or []


async def upload_file(
    access_token: str,
    path: str,
    content: bytes,
    mode: str = "overwrite",
) -> dict:
    """POST /2/files/upload. Path must start with /. Mode: add | overwrite | update."""
    args = {"path": path, "mode": mode, "autorename": False, "mute": True}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://content.dropboxapi.com/2/files/upload",
            content=content,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/octet-stream",
                # Dropbox API arg goes in this header for content endpoints.
                "Dropbox-API-Arg": __json_dumps(args),
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Dropbox upload failed: {resp.status_code} {resp.text}")
    return resp.json() or {}


def __json_dumps(d: dict) -> str:
    import json as _json
    return _json.dumps(d, separators=(",", ":"))
