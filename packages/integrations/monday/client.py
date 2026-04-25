from __future__ import annotations

import httpx
from supabase import Client

from packages.integrations.monday.oauth import (
    GRAPHQL_ENDPOINT,
    OAuthTokens,
)

PROVIDER = "monday"


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
    row = {
        "org_id": org_id,
        "provider": PROVIDER,
        "status": "active",
        "access_token": tokens.access_token,
        # No refresh / expiry on monday.com — these stay null.
        "refresh_token": None,
        "token_expires_at": None,
        "scopes": tokens.scope.split() if tokens.scope else [],
        "metadata": account,
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


# ── GraphQL helpers used by future agent tools ────────────────────────────

async def graphql(access_token: str, query: str, variables: dict | None = None) -> dict:
    """Run a GraphQL query against monday.com. Returns the `data` payload.

    monday.com's auth header takes the bare token (no `Bearer` prefix), and
    they recommend pinning an API-Version header so schema changes don't
    silently break clients.
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            GRAPHQL_ENDPOINT,
            json={"query": query, "variables": variables or {}},
            headers={
                "Authorization": access_token,
                "Content-Type": "application/json",
                "API-Version": "2024-01",
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"monday.com GraphQL HTTP {resp.status_code}: {resp.text}")
    body = resp.json() or {}
    if body.get("errors"):
        raise RuntimeError(f"monday.com GraphQL errors: {body['errors']}")
    return body.get("data") or {}


async def list_boards(access_token: str, limit: int = 25) -> list[dict]:
    data = await graphql(
        access_token,
        "query($limit: Int!) { boards(limit: $limit) { id name state } }",
        {"limit": limit},
    )
    return data.get("boards") or []


async def create_item(
    access_token: str,
    board_id: str,
    item_name: str,
    column_values: dict | None = None,
) -> dict:
    data = await graphql(
        access_token,
        """
        mutation($board: ID!, $name: String!, $cols: JSON) {
          create_item(board_id: $board, item_name: $name, column_values: $cols) {
            id
            name
          }
        }
        """,
        {
            "board": board_id,
            "name": item_name,
            "cols": __json_dumps(column_values or {}),
        },
    )
    return (data.get("create_item") or {}) if data else {}


def __json_dumps(d: dict) -> str:
    import json as _json
    return _json.dumps(d, separators=(",", ":"))
