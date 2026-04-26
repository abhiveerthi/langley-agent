"""Slack interactive components webhook (button clicks + modal submits).

This is the inbound side of approval cards: when a user clicks Approve
or Reject in #backroom-publisher, Slack POSTs here. We verify the
signing secret (same one used for events), dispatch by `type`, and
either open a feedback modal or kick off the resume flow.

Phase C handles three payload shapes:

  - block_actions / approve  : resume the run as approved
  - block_actions / reject   : open a modal asking for feedback
  - view_submission          : the modal was submitted; resume as rejected
                                with the user's feedback

Slack imposes a 3-second response timeout, so each path acks immediately
(empty 200 for block_actions, response_action="clear" for views) and
dispatches the actual work via asyncio.create_task.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, Response
from supabase import create_client

from app.config import get_settings
from app.services import slack_runner
from packages.integrations.slack import client as slack_client
from packages.integrations.slack.blocks import (
    build_reject_modal,
    build_resolution_card,
)
from packages.integrations.slack.events import verify_signing_secret


router = APIRouter(tags=["slack-interactive"])
log = logging.getLogger(__name__)


@router.post("/slack/interactive")
async def slack_interactive(request: Request) -> Response:
    settings = get_settings()
    raw_body = await request.body()

    if not verify_signing_secret(
        request.headers, raw_body, settings.slack_signing_secret
    ):
        raise HTTPException(401, "Bad Slack signature")

    # Slack interactive sends application/x-www-form-urlencoded with a
    # single `payload` field that's URL-encoded JSON. Different shape from
    # the events webhook (raw JSON).
    form = parse_qs(raw_body.decode("utf-8"))
    payload_raw = (form.get("payload") or [""])[0]
    if not payload_raw:
        raise HTTPException(400, "Missing payload")
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid payload JSON")

    payload_type = payload.get("type")

    if payload_type == "block_actions":
        return await _handle_block_actions(payload)

    if payload_type == "view_submission":
        return await _handle_view_submission(payload)

    # url_verification on this endpoint isn't a thing — Slack uses Events
    # API for that. Anything else is a no-op ack.
    return Response(status_code=200)


# ── block_actions: Approve / Reject button clicks ─────────────────────────

async def _handle_block_actions(payload: dict) -> Response:
    actions = payload.get("actions") or []
    if not actions:
        return Response(status_code=200)
    action = actions[0]
    action_id = action.get("action_id")
    approval_id = action.get("value") or ""
    user = payload.get("user") or {}
    slack_user_id = user.get("id") or ""

    if action_id == "approve":
        # Ack immediately; do the resume in the background since orchestrator
        # runs blow past Slack's 3s deadline.
        asyncio.create_task(_dispatch_resolution(
            approval_id=approval_id,
            decision="approved",
            slack_user_id=slack_user_id,
            payload=payload,
        ))
        return Response(status_code=200)

    if action_id == "reject":
        # Reject opens the feedback modal synchronously (trigger_id is
        # short-lived ~3s). The resume actually fires when the modal is
        # submitted (view_submission below).
        trigger_id = payload.get("trigger_id")
        if not trigger_id or not approval_id:
            return Response(status_code=200)
        await _open_reject_modal(approval_id, trigger_id, payload)
        return Response(status_code=200)

    return Response(status_code=200)


# ── view_submission: modal submitted with feedback ────────────────────────

async def _handle_view_submission(payload: dict) -> Response:
    view = payload.get("view") or {}
    if view.get("callback_id") != "reject_with_feedback":
        return Response(status_code=200)
    approval_id = view.get("private_metadata") or ""
    state = view.get("state") or {}
    feedback_value = (
        ((state.get("values") or {}).get("feedback_block") or {}).get("feedback") or {}
    ).get("value") or ""
    user = payload.get("user") or {}
    slack_user_id = user.get("id") or ""

    asyncio.create_task(_dispatch_resolution(
        approval_id=approval_id,
        decision="rejected",
        feedback=feedback_value,
        slack_user_id=slack_user_id,
        payload=payload,
    ))
    # Slack closes the modal automatically on plain 200.
    return Response(status_code=200)


# ── Background dispatch ───────────────────────────────────────────────────

async def _dispatch_resolution(
    *,
    approval_id: str,
    decision: str,
    slack_user_id: str,
    payload: dict,
    feedback: str | None = None,
) -> None:
    """Run after the user clicks Approve or submits the Reject modal:
      1. chat.update the original card to its resolved form (buttons gone)
      2. Resume the orchestrator via slack_runner.handle_resume
      3. handle_resume posts continuation tokens / next approval card

    The reviewer_user_id passed to the orchestrator is the *Marcus* user
    id (resolved from the Slack user via email match), since approvals
    audit fields reference `users.id`. If we can't resolve the Slack
    user, we still update the card but skip the resume — better to leave
    the gate "unresolved" in the orchestrator than to write a fake user.
    """
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_key):
        log.warning("slack_interactive: Supabase not configured")
        return
    supabase: Any = create_client(
        settings.supabase_url, settings.supabase_service_key
    )

    approval = (
        supabase.table("approvals")
        .select("*")
        .eq("id", approval_id)
        .limit(1)
        .execute()
    )
    if not approval.data:
        log.warning(f"slack_interactive: approval {approval_id} not found")
        return
    row = approval.data[0]

    slack_channel_id = row.get("slack_channel_id")
    slack_message_ts = row.get("slack_message_ts")

    # Resolve Slack user → Marcus user via the same email-match path used
    # in the events flow.
    bot_token = _bot_token_for_channel(supabase, slack_channel_id)
    if not bot_token:
        log.warning("slack_interactive: no bot token for channel")
        return

    from packages.integrations.slack.identity import resolve_marcus_user
    team_id = _team_id_for_channel(supabase, slack_channel_id)
    ident = await resolve_marcus_user(
        supabase=supabase,
        slack_team_id=team_id,
        slack_user_id=slack_user_id,
        slack_bot_token=bot_token,
    )

    # 1) Update the original card to its resolved form.
    if slack_channel_id and slack_message_ts:
        try:
            original = await slack_client.get_message(
                bot_token, slack_channel_id, slack_message_ts
            )
            if original:
                resolved = build_resolution_card(
                    original_card={"blocks": original.get("blocks") or []},
                    decision=decision,
                    reviewer_user_id=slack_user_id,
                    feedback=feedback,
                )
                await slack_client.update_message(
                    bot_token,
                    slack_channel_id,
                    slack_message_ts,
                    resolved["text"],
                    blocks=resolved["blocks"],
                )
        except Exception as e:
            log.exception(f"slack_interactive: card update failed: {e!r}")

    # 2) Resume the orchestrator. Skip if we couldn't resolve the Marcus
    # user — auditing requires a real users.id.
    if ident is None:
        log.warning("slack_interactive: Slack user not linked; skipping resume")
        return
    try:
        await slack_runner.handle_resume(
            supabase=supabase,
            approval_id=approval_id,
            decision=decision,
            feedback=feedback,
            reviewer_user_id=ident["user_id"],
        )
    except Exception:
        log.exception("slack_interactive: resume dispatch failed")


async def _open_reject_modal(approval_id: str, trigger_id: str, payload: dict) -> None:
    """Open the feedback modal synchronously. Trigger ids are short-lived,
    so we can't background this — but views.open is fast, ~250ms typical."""
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_key):
        return
    supabase: Any = create_client(
        settings.supabase_url, settings.supabase_service_key
    )

    approval = (
        supabase.table("approvals")
        .select("slack_channel_id")
        .eq("id", approval_id)
        .limit(1)
        .execute()
    )
    if not approval.data:
        return
    slack_channel_id = approval.data[0].get("slack_channel_id")
    bot_token = _bot_token_for_channel(supabase, slack_channel_id)
    if not bot_token:
        return
    try:
        await slack_client.open_modal(
            bot_token, trigger_id, build_reject_modal(approval_id)
        )
    except Exception:
        log.exception("slack_interactive: open_modal failed")


# ── Lookup helpers ────────────────────────────────────────────────────────

def _bot_token_for_channel(supabase: Any, slack_channel_id: str | None) -> str | None:
    if not slack_channel_id:
        return None
    chan = (
        supabase.table("slack_channels")
        .select("slack_team_id")
        .eq("slack_channel_id", slack_channel_id)
        .limit(1)
        .execute()
    )
    if not chan.data:
        return None
    team_id = chan.data[0]["slack_team_id"]
    integ = (
        supabase.table("integrations")
        .select("access_token")
        .eq("provider", "slack")
        .filter("metadata->>team_id", "eq", team_id)
        .limit(1)
        .execute()
    )
    return integ.data[0]["access_token"] if integ.data else None


def _team_id_for_channel(supabase: Any, slack_channel_id: str | None) -> str:
    if not slack_channel_id:
        return ""
    chan = (
        supabase.table("slack_channels")
        .select("slack_team_id")
        .eq("slack_channel_id", slack_channel_id)
        .limit(1)
        .execute()
    )
    return chan.data[0]["slack_team_id"] if chan.data else ""
