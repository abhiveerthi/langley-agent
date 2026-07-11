"""
Monday.com webhook receiver — the Content Agent's review-decision inbox.

Monday fires a POST here whenever a column changes on an org's review
board (subscription created by review.ensure_review_board). Two payloads:

  1. Handshake: {"challenge": "..."} — echoed verbatim. Monday sends this
     while CREATING the webhook and expects the echo before activating it
     (which is why provisioning persists the secret BEFORE registering).
  2. Event: {"event": {"type": "update_column_value", "pulseId": ...,
     "columnId": "...", "value": {"label": {"text": "Approved"}}}} — a
     human flipped an item's status. We map the item back to its pipeline
     via content_review_items and apply the decision (content/review.py).

Auth model: Monday board webhooks aren't signed, so the subscription URL
embeds /{org_id}/{secret}. The secret lives in content_review_boards — a
service-role-only table (NOT agents.config, which org members can read via
GET /api/agents; the secret is this endpoint's only authentication).
Wrong secret → 404, indistinguishable from a nonexistent route.

Abuse hardening for an unauthenticated endpoint: org_id must parse as a
UUID and the body must be small BEFORE any DB round-trip; the secret check
is one PK lookup compared via hmac.compare_digest; events for columns
other than the provisioned Approval column are ignored (a user adding a
second status column to the board must not drive review decisions).
"""
from __future__ import annotations

import hmac
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger("monday_webhooks")

router = APIRouter(tags=["monday-webhooks"])

# Monday event payloads are tiny (<2KB). Anything bigger is not Monday.
MAX_BODY_BYTES = 64 * 1024

_HANDLED_EVENTS = ("update_column_value", "change_column_value")


def _service_client():
    from app.config import get_settings
    from supabase import create_client

    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_key):
        return None
    return create_client(settings.supabase_url, settings.supabase_service_key)


def _board_row(supabase, org_id: str) -> dict | None:
    """The org's provisioned review-board row (service-role-only table)."""
    try:
        resp = (
            supabase.table("content_review_boards")
            .select("*")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception:
        return None


@router.post("/webhooks/monday/{org_id}/{secret}")
async def monday_webhook(org_id: str, secret: str, request: Request):
    # Cheap rejects first — no DB work for obviously-forged requests.
    try:
        uuid.UUID(org_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="not found")
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload too large")

    supabase = _service_client()
    if supabase is None:
        raise HTTPException(status_code=503, detail="service unavailable")

    board = _board_row(supabase, org_id)
    expected = (board or {}).get("webhook_secret") or ""
    if not expected or not hmac.compare_digest(secret, expected):
        raise HTTPException(status_code=404, detail="not found")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    if "challenge" in body:
        return {"challenge": body["challenge"]}

    event = body.get("event") or {}
    if event.get("type") not in _HANDLED_EVENTS:
        return {"ok": True, "ignored": event.get("type")}

    # Only the provisioned Approval column drives decisions.
    status_column_id = board.get("status_column_id")
    event_column = event.get("columnId")
    if status_column_id and event_column and str(event_column) != str(status_column_id):
        return {"ok": True, "ignored": f"column {event_column}"}

    item_id = event.get("pulseId") or event.get("itemId")
    label = (((event.get("value") or {}).get("label")) or {}).get("text")
    if not item_id:
        return {"ok": True, "ignored": "no item id"}

    from packages.agents.content.review import apply_status_change

    result = apply_status_change(
        supabase, org_id, monday_item_id=str(item_id), label=label
    )
    if result:
        log.info(
            "Monday review decision org=%s video=%s role=%s decision=%s",
            org_id, result["video_id"], result["role"], result["decision"],
        )
        # The owner's FINAL approval IS the publish trigger — fan out
        # immediately (noon CST target) rather than waiting for the next
        # scheduler sweep. run_publish CAS-claims approved → publishing, so
        # the sweep's catch-up pass can never double-publish.
        if result["role"] == "final" and result["decision"] == "approved":
            _spawn_publish(supabase, org_id, result["video_id"])
    return {"ok": True, "applied": bool(result)}


# Strong refs to in-flight publish tasks (mirrors scheduler._content_tasks).
_publish_tasks: set = set()


def _spawn_publish(supabase, org_id: str, video_id: str) -> None:
    import asyncio

    from packages.agents.content.publish import run_publish

    async def _run():
        try:
            summary = await run_publish(supabase, org_id, video_id)
            log.info("Publish run for org=%s video=%s: %s", org_id, video_id, summary)
        except Exception:
            log.exception("Publish run crashed for org=%s video=%s", org_id, video_id)

    task = asyncio.create_task(_run())
    _publish_tasks.add(task)
    task.add_done_callback(_publish_tasks.discard)
