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


async def add_update(access_token: str, item_id: str, body: str) -> dict:
    """Post an update (comment) onto an item. The Content Agent uses this to
    put the AI-drafted copy INSIDE each review item so the reviewer QAs tone
    right on the board — no other tool, no copying text around."""
    data = await graphql(
        access_token,
        """
        mutation($item: ID!, $body: String!) {
          create_update(item_id: $item, body: $body) { id }
        }
        """,
        {"item": item_id, "body": body[:20000]},
    )
    return data.get("create_update") or {}


async def create_board(
    access_token: str, board_name: str, *, board_kind: str = "public"
) -> dict:
    """Create a board; returns {id, name}. Used by the Content Agent to
    provision its dedicated review-queue board."""
    data = await graphql(
        access_token,
        """
        mutation($name: String!, $kind: BoardKind!) {
          create_board(board_name: $name, board_kind: $kind) { id name }
        }
        """,
        {"name": board_name, "kind": board_kind},
    )
    return data.get("create_board") or {}


async def create_status_column(
    access_token: str,
    board_id: str,
    title: str,
    labels: list[str],
) -> dict:
    """Create a status column with custom labels; returns {id, title}.

    Label INDEXES are positional ("0", "1", ...) but consumers must match on
    label TEXT (webhook payloads carry value.label.text) — indexes are a
    Monday-internal detail that can shift if labels are edited in the UI.
    """
    defaults = {"labels": {str(i): label for i, label in enumerate(labels)}}
    data = await graphql(
        access_token,
        """
        mutation($board: ID!, $title: String!, $defaults: JSON) {
          create_column(
            board_id: $board, title: $title,
            column_type: status, defaults: $defaults
          ) { id title }
        }
        """,
        {"board": board_id, "title": title, "defaults": __json_dumps(defaults)},
    )
    return data.get("create_column") or {}


async def create_webhook(
    access_token: str,
    board_id: str,
    url: str,
    *,
    event: str = "change_column_value",
) -> dict:
    """Subscribe `url` to a board's column-change events; returns {id}.

    Monday validates the URL with a challenge POST during this call — the
    receiving endpoint must already be live and echoing {"challenge": ...}.
    """
    data = await graphql(
        access_token,
        """
        mutation($board: ID!, $url: String!, $event: WebhookEventType!) {
          create_webhook(board_id: $board, url: $url, event: $event) { id board_id }
        }
        """,
        {"board": board_id, "url": url, "event": event},
    )
    return data.get("create_webhook") or {}


def __json_dumps(d: dict) -> str:
    import json as _json
    return _json.dumps(d, separators=(",", ":"))
