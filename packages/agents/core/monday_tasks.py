"""
Agent-facing monday.com task delegation + progress logging.

The roadmap's Manager / Comms agents are supposed to "delegate tasks" and
"log progress on monday.com". This module is the monday.com counterpart to
`packages/agents/core/tasks.py` (which drops work into the internal `/app/tasks`
workspace) — it pushes work into the creator's connected monday.com boards via
the OAuth GraphQL client.

Connection resolution mirrors the integrations router: we read the org's row
from the `integrations` table (provider = "monday") and pull the long-lived
`access_token` off it. monday.com tokens never expire and have no refresh
token (see `monday/oauth.py`), so a single read is enough — there's no
refresh dance like Gmail.

Best-effort by design: every helper here swallows errors and no-ops gracefully
when monday.com isn't connected. A failed monday write is far less bad than a
failed agent run — the agent's primary work (drafting the pitch, sending the
email) has typically already succeeded by the time we delegate/log here.
"""
from __future__ import annotations

import uuid
from typing import Any

from packages.integrations.context import current_supabase
from packages.integrations.monday import client as monday_client


def _is_real_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _resolve_access_token(org_id: str | None, supabase: Any) -> str | None:
    """Load the org's monday.com access token from the `integrations` table.

    Same path the integrations router uses (`monday_client.get_connection`).
    Returns None when monday isn't connected, the connection is in an error
    state, or anything in the lookup blows up — every caller treats None as
    "monday not available, no-op".
    """
    if not _is_real_uuid(org_id) or supabase is None:
        return None
    try:
        conn = monday_client.get_connection(supabase, org_id)
    except Exception:
        return None
    if not conn:
        return None
    # An errored connection still has a (possibly stale) token; skip it so we
    # don't hammer monday with calls that will just fail again.
    if conn.get("status") == "error":
        return None
    return conn.get("access_token") or None


async def monday_create_item(
    org_id: str | None,
    *,
    board_id: str,
    item_name: str,
    column_values: dict[str, Any] | None = None,
    group_id: str | None = None,
) -> str | None:
    """Create a monday.com item (task) on a board — agent delegation entry point.

    Returns the new item id, or None when the write was skipped (no monday
    connection, dev org, blank inputs) or failed. Never raises.

    `group_id` targets a specific board group (column/section). monday's
    `create_item` mutation accepts an optional `group_id`; we only thread it
    through when supplied so the default-group behaviour is preserved.
    """
    if not (board_id or "").strip() or not (item_name or "").strip():
        return None

    supabase = current_supabase.get()
    token = _resolve_access_token(org_id, supabase)
    if not token:
        return None

    try:
        if group_id:
            data = await monday_client.graphql(
                token,
                """
                mutation($board: ID!, $name: String!, $cols: JSON, $group: String) {
                  create_item(board_id: $board, item_name: $name, column_values: $cols, group_id: $group) {
                    id
                    name
                  }
                }
                """,
                {
                    "board": board_id,
                    "name": item_name.strip()[:255],
                    "cols": __json_dumps(column_values or {}),
                    "group": group_id,
                },
            )
            item = (data.get("create_item") or {}) if data else {}
        else:
            item = await monday_client.create_item(
                token,
                board_id=board_id,
                item_name=item_name.strip()[:255],
                column_values=column_values,
            )
    except Exception as e:
        print(f"[monday_tasks] monday_create_item failed: {e!r}", flush=True)
        return None

    return (item or {}).get("id")


async def monday_log_progress(
    org_id: str | None,
    *,
    board_id: str,
    item_name: str,
    note: str,
) -> str | None:
    """Log a progress update onto monday.com.

    Creates an item representing the progress entry, then posts the `note` as
    an update (the monday equivalent of a comment) on that item so the detail
    lands in the activity feed. If the update post fails we still return the
    item id — the item itself captures that progress happened.

    Returns the item id, or None when monday isn't connected / inputs are blank
    / the create failed. Never raises.
    """
    if not (board_id or "").strip() or not (item_name or "").strip():
        return None

    supabase = current_supabase.get()
    token = _resolve_access_token(org_id, supabase)
    if not token:
        return None

    try:
        item = await monday_client.create_item(
            token,
            board_id=board_id,
            item_name=item_name.strip()[:255],
            column_values=None,
        )
    except Exception as e:
        print(f"[monday_tasks] monday_log_progress create failed: {e!r}", flush=True)
        return None

    item_id = (item or {}).get("id")
    if not item_id:
        return None

    # Best-effort: attach the note as an update on the new item. A failed
    # update post does not lose the item — return its id regardless.
    if (note or "").strip():
        try:
            await monday_client.graphql(
                token,
                """
                mutation($item: ID!, $body: String!) {
                  create_update(item_id: $item, body: $body) { id }
                }
                """,
                {"item": item_id, "body": note.strip()},
            )
        except Exception as e:
            print(f"[monday_tasks] monday_log_progress update failed: {e!r}", flush=True)

    return item_id


async def monday_list_boards(org_id: str | None) -> list[dict]:
    """List the org's monday.com boards (id/name/state). Best-effort.

    Returns an empty list when monday isn't connected or the call fails — the
    agent treats an empty list as "no boards to delegate into".
    """
    supabase = current_supabase.get()
    token = _resolve_access_token(org_id, supabase)
    if not token:
        return []
    try:
        return await monday_client.list_boards(token)
    except Exception as e:
        print(f"[monday_tasks] monday_list_boards failed: {e!r}", flush=True)
        return []


def __json_dumps(d: dict) -> str:
    import json as _json
    return _json.dumps(d, separators=(",", ":"))
