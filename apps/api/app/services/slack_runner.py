"""Slack-originated agent runs.

This module is the Slack equivalent of `apps/api/app/routers/stream.py`'s
HTTP handler: it takes a Slack message event, resolves it to a Marcus
(org, user, thread), invokes the existing graph orchestrator, accumulates
the SSE stream, and posts the final reply back to the Slack thread.

Phase A scope:
  - Publisher only (only `#marcus-publisher` channels are wired up at
    install time; this runner reads `agent_slug` from `slack_channels`).
  - Final-message-only response. Mid-stream "thinking..." updates,
    tool-call surfacing, and approval cards are deferred to Phase C/D.
  - Email-match identity. Per-user OAuth fallback is Phase B+.

Per-Slack-thread = per-Marcus-thread:
  - A top-level Slack message starts a new Marcus thread (UUID generated
    here, persisted to `slack_channels` keyed on the user's message ts).
  - Replies in the same Slack thread reuse the Marcus thread, so agent
    context (and the LangGraph checkpointer state) accumulates.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.auth import with_tool_context
from app.services.graph_orchestrator import stream_new_run
from packages.integrations.slack import client as slack_client
from packages.integrations.slack.identity import resolve_marcus_user


LINK_ACCOUNT_FALLBACK = (
    "I can't link your Slack account to Marcus — your Slack email doesn't "
    "match a Marcus user in this workspace's org. Sign in to Marcus with the "
    "same email you use on Slack and try again."
)


async def handle_message(
    *,
    supabase: Any,
    slack_team_id: str,
    slack_channel_id: str,
    slack_user_id: str,
    slack_thread_ts: str | None,
    slack_message_ts: str,
    text: str,
) -> None:
    """Run the agent for one inbound Slack message and post a reply.

    Caller (the events webhook) is expected to dispatch this in a
    background task — the orchestrator can take 30+ seconds and Slack
    times the webhook out at 3.
    """
    chan = _lookup_channel_mapping(supabase, slack_channel_id)
    if chan is None:
        # Channel isn't provisioned for any agent; ignore quietly.
        return
    org_id = chan["org_id"]
    agent_slug = chan["agent_slug"]

    bot_token = _lookup_bot_token(supabase, slack_team_id)
    if not bot_token:
        # Workspace's Slack install was deleted; nothing to do.
        return

    ident = await resolve_marcus_user(
        supabase=supabase,
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
        slack_bot_token=bot_token,
    )
    if ident is None:
        await slack_client.post_message_in_thread(
            bot_token,
            slack_channel_id,
            LINK_ACCOUNT_FALLBACK,
            thread_ts=slack_thread_ts or slack_message_ts,
        )
        return

    # Top-level Slack message → root_ts is the user's own ts.
    # Reply in an existing Slack thread → root_ts is the parent's thread_ts.
    root_ts = slack_thread_ts or slack_message_ts
    marcus_thread_id = _resolve_marcus_thread(
        supabase,
        org_id=org_id,
        agent_slug=agent_slug,
        slack_team_id=slack_team_id,
        slack_channel_id=slack_channel_id,
        slack_thread_root_ts=root_ts,
    )

    _ensure_thread(
        supabase,
        thread_id=marcus_thread_id,
        org_id=org_id,
        user_id=ident["user_id"],
        title=f"#marcus-{agent_slug} (Slack)",
    )

    _insert_message(
        supabase,
        thread_id=marcus_thread_id,
        role="user",
        content=text,
        metadata={
            "source": "slack",
            "slack_user_id": slack_user_id,
            "slack_message_ts": slack_message_ts,
            "slack_channel_id": slack_channel_id,
        },
    )

    accumulated: list[str] = []
    error_msg: str | None = None

    async for sse in with_tool_context(
        stream_new_run(
            agent_slug=agent_slug,
            message=text,
            thread_id=marcus_thread_id,
            org_id=org_id,
            user_id=ident["user_id"],
        ),
        org_id=org_id,
        user_id=ident["user_id"],
        supabase=supabase,
    ):
        ev = _parse_sse(sse)
        if ev is None:
            continue
        if ev["type"] == "token":
            content = (ev.get("data") or {}).get("content") or ""
            if content:
                accumulated.append(content)
        elif ev["type"] == "error":
            error_msg = (ev.get("data") or {}).get("message") or "unknown error"
        # Phase A: ignore tool_call_*, waiting_approval, done.

    if error_msg:
        final = f"Run failed: {error_msg}"
    else:
        final = "".join(accumulated).strip() or "(no response)"

    _insert_message(
        supabase,
        thread_id=marcus_thread_id,
        role="assistant",
        content=final,
        metadata={"source": "slack"},
    )

    await slack_client.post_message_in_thread(
        bot_token,
        slack_channel_id,
        final,
        thread_ts=root_ts,
    )


# ── Lookup helpers ─────────────────────────────────────────────────────────

def _lookup_channel_mapping(supabase: Any, slack_channel_id: str) -> dict | None:
    """The "channel mapping" row for this Slack channel — the one with
    slack_thread_root_ts IS NULL. Tells us which agent + org owns it."""
    resp = (
        supabase.table("slack_channels")
        .select("org_id, agent_slug")
        .eq("slack_channel_id", slack_channel_id)
        .is_("slack_thread_root_ts", "null")
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _lookup_bot_token(supabase: Any, slack_team_id: str) -> str | None:
    """Bot token (xoxb-) for this Slack workspace, by team_id."""
    resp = (
        supabase.table("integrations")
        .select("access_token")
        .eq("provider", "slack")
        .filter("metadata->>team_id", "eq", slack_team_id)
        .limit(1)
        .execute()
    )
    return resp.data[0]["access_token"] if resp.data else None


def _resolve_marcus_thread(
    supabase: Any,
    *,
    org_id: str,
    agent_slug: str,
    slack_team_id: str,
    slack_channel_id: str,
    slack_thread_root_ts: str,
) -> str:
    """Find or create the Marcus thread for this Slack thread.

    First time we see a given (channel, root_ts) we mint a fresh Marcus
    thread UUID and persist the mapping; reply messages on the same Slack
    thread reuse it.
    """
    existing = (
        supabase.table("slack_channels")
        .select("marcus_thread_id")
        .eq("slack_channel_id", slack_channel_id)
        .eq("slack_thread_root_ts", slack_thread_root_ts)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["marcus_thread_id"]

    marcus_thread_id = str(uuid4())
    supabase.table("slack_channels").insert(
        {
            "org_id": org_id,
            "agent_slug": agent_slug,
            "slack_team_id": slack_team_id,
            "slack_channel_id": slack_channel_id,
            "slack_thread_root_ts": slack_thread_root_ts,
            "marcus_thread_id": marcus_thread_id,
        }
    ).execute()
    return marcus_thread_id


def _ensure_thread(
    supabase: Any,
    *,
    thread_id: str,
    org_id: str,
    user_id: str,
    title: str,
) -> None:
    """Idempotent upsert of a `threads` row, mirroring the orchestrator's
    _ensure_thread_row but with a Slack-flavored title and the resolved
    user_id attached so the web chat history surfaces it correctly."""
    try:
        supabase.table("threads").upsert(
            {
                "id": thread_id,
                "org_id": org_id,
                "user_id": user_id,
                "title": title,
                "status": "active",
            },
            on_conflict="id",
        ).execute()
    except Exception as e:
        # Non-fatal: if this fails the messages insert below will surface
        # the FK error with the real diagnostic.
        print(f"[slack_runner] _ensure_thread failed: {e!r}", flush=True)


def _insert_message(
    supabase: Any,
    *,
    thread_id: str,
    role: str,
    content: str,
    metadata: dict,
) -> None:
    try:
        supabase.table("messages").insert(
            {
                "thread_id": thread_id,
                "role": role,
                "content": content,
                "metadata": metadata,
            }
        ).execute()
    except Exception as e:
        # Persistence is best-effort; the user-visible reply still goes to
        # Slack. Log so we can spot if the chat history page misses runs.
        print(f"[slack_runner] message insert failed: {e!r}", flush=True)


def _parse_sse(line: str) -> dict | None:
    """The orchestrator's _sse() emits `data: {json}\\n\\n` strings. Parse
    one back into a dict so the runner can pattern-match on `type`."""
    line = line.strip()
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None
