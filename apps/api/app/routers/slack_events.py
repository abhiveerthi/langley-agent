"""Slack Events API webhook.

This router accepts Slack's Events API callbacks (signed by the app's
signing secret) and dispatches qualifying message events to the Slack
runner. It must respond within 3 seconds — Slack retries otherwise — so
the actual agent run happens in a background task.

Phase A subscribes only to `message.groups` (private channel messages),
which is the surface needed to wire the per-agent channels created by
the OAuth callback. `app_mention`, `message.im`, etc. are deferred.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from supabase import create_client

from app.config import get_settings
from app.services import slack_runner
from packages.integrations.slack.events import verify_signing_secret


router = APIRouter(tags=["slack-events"])
log = logging.getLogger(__name__)


@router.post("/slack/events")
async def slack_events(request: Request) -> Response:
    settings = get_settings()
    raw_body = await request.body()

    # Slack sends url_verification BEFORE the app is registered for events,
    # so we have to handle it before signature verification fails open.
    # The challenge response itself is unsigned; that's by design (Slack
    # uses it to confirm the URL accepts JSON, then signs everything after).
    try:
        body = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    if body.get("type") == "url_verification":
        return Response(
            content=json.dumps({"challenge": body.get("challenge")}),
            media_type="application/json",
        )

    if not verify_signing_secret(
        request.headers, raw_body, settings.slack_signing_secret
    ):
        raise HTTPException(401, "Bad Slack signature")

    if body.get("type") != "event_callback":
        # Other top-level types (rate_limit, etc.) — ack without dispatch.
        return Response(status_code=200)

    event = body.get("event") or {}
    if not _is_user_message(event):
        return Response(status_code=200)

    # Slack times the webhook out at 3s; Publisher runs are slow. Dispatch.
    asyncio.create_task(_dispatch(body, event))
    return Response(status_code=200)


def _is_user_message(event: dict) -> bool:
    """Filter out events the runner shouldn't act on:
      - non-message types
      - bot-authored messages (avoid feedback loops)
      - subtypes like message_changed / channel_join / message_deleted
        which deliver via the same `message` event but aren't human input

    EXCEPTION: `file_share` IS human input — screenshots and voice notes
    arrive as message events with that subtype (and often no text at all).
    Agent #6's whole Slack surface lives on this branch.
    """
    if event.get("type") != "message":
        return False
    if event.get("bot_id"):
        return False
    subtype = event.get("subtype")
    if subtype == "file_share":
        return bool(event.get("user") and event.get("files"))
    if subtype:
        return False
    if not event.get("user") or not event.get("text"):
        return False
    return True


async def _dispatch(body: dict, event: dict) -> None:
    """Run the agent for one message event. Runs detached from the
    request — exceptions here can't propagate to Slack, so log them."""
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_key):
        log.warning("slack_events: Supabase not configured; skipping dispatch")
        return

    # Service-role client: cross-tenant routing, no per-request user. RLS
    # is bypassed; we authorise via the email-match resolver inside the
    # runner instead.
    supabase: Any = create_client(
        settings.supabase_url, settings.supabase_service_key
    )

    try:
        await slack_runner.handle_message(
            supabase=supabase,
            slack_team_id=body.get("team_id") or "",
            slack_channel_id=event["channel"],
            slack_user_id=event["user"],
            slack_thread_ts=event.get("thread_ts"),
            slack_message_ts=event["ts"],
            text=event.get("text") or "",
            files=event.get("files") or [],
        )
    except Exception:
        log.exception("slack_events: dispatch failed")
