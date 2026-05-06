"""
Agent dispatch for team channels.

When a user posts `@strategist what should we make next?` in a channel,
this helper runs the named agent against that message and posts the
agent's final response back into the channel as a `sender_agent_id`
message. Failures (missing slug, paused approval gate, agent crash)
all post a fallback message — channels with no response feel broken,
so the user-visible signal is what matters.

Called from `channels.create_message` via FastAPI BackgroundTasks. Any
raise here would be swallowed by BackgroundTasks; we log + post a
fallback instead so the channel always reflects what happened.
"""
from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import AIMessage

from app.auth import with_tool_context
from app.services.approval_store import get_approval_store
from app.services.graph_orchestrator import (
    _compile_agent,
    stream_new_run,
    stream_resume_approved,
    stream_resume_rejected,
)
from packages.agents.registry import AGENT_REGISTRY, get_agent


def _resolve_agent_id(supabase, *, org_id: str, slug: str) -> str | None:
    """Look up the org-scoped `agents.id` for a given slug."""
    try:
        resp = (
            supabase.table("agents")
            .select("id")
            .eq("org_id", org_id)
            .eq("slug", slug)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    if not resp.data:
        return None
    return resp.data[0].get("id")


def _post_channel_message(
    supabase,
    *,
    channel_id: str,
    org_id: str,
    sender_agent_id: str | None,
    body: str,
    in_reply_to_message_id: str | None,
    agent_run_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Insert a `channel_messages` row authored by an agent.

    Bypasses the user-side mention parser entirely — agent-authored
    messages must never re-trigger dispatch (would loop forever on
    e.g. `@publisher` quoting a user's prompt back).

    `metadata` rides on the `metadata` jsonb column. `{kind: "approval",
    approval_id: ...}` triggers the FE to render an inline approval card
    instead of plain text. The body is still rendered as a fallback (and
    used by message search), so always pass a sensible human description.
    """
    payload = {
        "channel_id": channel_id,
        "org_id": org_id,
        "sender_agent_id": sender_agent_id,
        "body": body,
        "mentioned_user_ids": [],
        "mentioned_agent_slugs": [],
        "in_reply_to_message_id": in_reply_to_message_id,
        "agent_run_id": agent_run_id,
        "metadata": metadata or {},
    }
    try:
        supabase.table("channel_messages").insert(payload).execute()
    except Exception as e:
        print(f"[channel_dispatch] post failed: {e!r}", flush=True)


def _resolve_pending_approval_id(supabase, *, org_id: str, thread_id: str) -> str | None:
    """Find the approvals row the agent just created when it paused.

    The orchestrator inserts an approvals row keyed on (org_id, thread_id)
    immediately before yielding the `waiting_approval` SSE event. Our
    dispatch ran the SSE generator to completion, so by the time we
    inspect state.next == ['approval_gate'], that row exists. Latest
    pending approval for this thread is the one we want."""
    try:
        resp = (
            supabase.table("approvals")
            .select("id")
            .eq("org_id", org_id)
            .eq("thread_id", thread_id)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        print(f"[channel_dispatch] approval lookup failed: {e!r}", flush=True)
        return None
    if not resp.data:
        return None
    return resp.data[0].get("id")


async def _drain_run(
    *,
    agent_slug: str,
    triggering_message_body: str,
    thread_id: str,
    org_id: str,
    user_id: str,
    supabase: Any,
) -> None:
    """Run `stream_new_run` to completion (drain the SSE generator).

    Wraps the generator in `with_tool_context` so agent tools can read
    org_id / user_id / supabase via ContextVars. The events themselves
    are discarded — the final response comes from `aget_state` after
    the generator finishes.
    """
    gen = with_tool_context(
        stream_new_run(
            agent_slug=agent_slug,
            message=triggering_message_body,
            thread_id=thread_id,
            org_id=org_id,
            user_id=user_id,
        ),
        org_id=org_id,
        user_id=user_id,
        supabase=supabase,
    )
    async for _event in gen:
        pass


async def dispatch_agent_to_channel(
    *,
    agent_slug: str,
    channel_id: str,
    org_id: str,
    user_id: str,
    triggering_message_id: str,
    triggering_message_body: str,
    supabase,
) -> None:
    """Run `agent_slug` on `triggering_message_body`, post the final
    response into the channel as a `sender_agent_id` message.

    Best-effort: any failure inserts a fallback message that surfaces
    what happened, never silently fails.
    """
    # 1. Slug must be a registered agent. Otherwise the FE rendered a
    # mention for a slug that isn't real for this workspace.
    if agent_slug not in AGENT_REGISTRY:
        _post_channel_message(
            supabase,
            channel_id=channel_id,
            org_id=org_id,
            sender_agent_id=None,
            body=f"@{agent_slug} isn't registered for this workspace.",
            in_reply_to_message_id=triggering_message_id,
        )
        return

    # 2. Resolve the agents row id for this org. If missing the slug
    # exists in code but isn't installed for this workspace.
    agent_row_id = _resolve_agent_id(supabase, org_id=org_id, slug=agent_slug)
    if agent_row_id is None:
        _post_channel_message(
            supabase,
            channel_id=channel_id,
            org_id=org_id,
            sender_agent_id=None,
            body=f"@{agent_slug} isn't registered for this workspace.",
            in_reply_to_message_id=triggering_message_id,
        )
        return

    # 3. Fresh thread per channel-mention. Channel mentions are ephemeral;
    # we don't want to thread them into a persistent 1-on-1 conversation.
    thread_id = str(uuid.uuid4())

    try:
        await _drain_run(
            agent_slug=agent_slug,
            triggering_message_body=triggering_message_body,
            thread_id=thread_id,
            org_id=org_id,
            user_id=user_id,
            supabase=supabase,
        )
    except Exception as e:
        print(f"[channel_dispatch] run failed: {e!r}", flush=True)
        _post_channel_message(
            supabase,
            channel_id=channel_id,
            org_id=org_id,
            sender_agent_id=agent_row_id,
            body=f"@{agent_slug} hit an error and couldn't respond.",
            in_reply_to_message_id=triggering_message_id,
        )
        return

    # 4-5. Inspect final state and post the appropriate message.
    await _post_agent_result(
        supabase,
        agent_slug=agent_slug,
        agent_row_id=agent_row_id,
        thread_id=thread_id,
        channel_id=channel_id,
        org_id=org_id,
        triggering_message_id=triggering_message_id,
    )


async def _post_agent_result(
    supabase,
    *,
    agent_slug: str,
    agent_row_id: str,
    thread_id: str,
    channel_id: str,
    org_id: str,
    triggering_message_id: str,
) -> None:
    """Inspect the agent's final graph state and post the right message.

    Three terminal cases:
      - `state.next` is non-empty → graph paused at an interrupt. Find
        the corresponding approvals row and post an approval-card
        channel message (FE renders inline buttons).
      - state has a final assistant message with content → post that
        text as the agent's reply.
      - neither → "ran but didn't produce a response" fallback.

    Used by both the fresh-dispatch path and the post-resume path so
    new pauses (multi-step approval workflows) keep posting cards into
    the same channel without divergent rendering.
    """
    try:
        agent = get_agent(agent_slug)
        app = await _compile_agent(agent)
        state = await app.aget_state({"configurable": {"thread_id": thread_id}})
    except Exception as e:
        print(f"[channel_dispatch] state fetch failed: {e!r}", flush=True)
        _post_channel_message(
            supabase,
            channel_id=channel_id,
            org_id=org_id,
            sender_agent_id=agent_row_id,
            body=f"@{agent_slug} hit an error and couldn't respond.",
            in_reply_to_message_id=triggering_message_id,
        )
        return

    if state.next:
        approval_id = _resolve_pending_approval_id(
            supabase, org_id=org_id, thread_id=thread_id,
        )
        if approval_id is None:
            _post_channel_message(
                supabase,
                channel_id=channel_id,
                org_id=org_id,
                sender_agent_id=agent_row_id,
                body=(
                    f"@{agent_slug} paused for your approval — open the "
                    f"[Approvals page](/app/approvals) to continue."
                ),
                in_reply_to_message_id=triggering_message_id,
            )
            return
        _post_channel_message(
            supabase,
            channel_id=channel_id,
            org_id=org_id,
            sender_agent_id=agent_row_id,
            body=f"@{agent_slug} needs your approval to continue.",
            in_reply_to_message_id=triggering_message_id,
            metadata={"kind": "approval", "approval_id": approval_id},
        )
        return

    messages = (state.values or {}).get("messages", [])
    final_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            if content:
                final_text = content
                break

    if not final_text.strip():
        _post_channel_message(
            supabase,
            channel_id=channel_id,
            org_id=org_id,
            sender_agent_id=agent_row_id,
            body=f"@{agent_slug} ran but didn't produce a response.",
            in_reply_to_message_id=triggering_message_id,
        )
        return

    _post_channel_message(
        supabase,
        channel_id=channel_id,
        org_id=org_id,
        sender_agent_id=agent_row_id,
        body=final_text,
        in_reply_to_message_id=triggering_message_id,
    )


async def dispatch_resume_to_channel(
    *,
    approval_id: str,
    decision: str,           # "approved" | "rejected"
    feedback: str | None,
    channel_id: str,
    org_id: str,
    user_id: str,
    triggering_message_id: str,
    supabase,
) -> None:
    """Resume a paused agent run from the inline approval card.

    Looks up the approval row to recover the agent slug + thread id,
    drains `stream_resume_approved` / `stream_resume_rejected` (which
    flips the approval row's status and continues the graph), then
    posts the agent's result (or next pause) back into the channel
    via the same `_post_agent_result` helper as the fresh-dispatch path.
    """
    # 1. Approval row tells us which agent + thread the resume targets.
    store = get_approval_store()
    try:
        row = await store.get(approval_id)
    except Exception as e:
        print(f"[channel_dispatch] approval lookup failed: {e!r}", flush=True)
        return
    if row is None:
        print(f"[channel_dispatch] approval {approval_id} not found", flush=True)
        return
    agent_slug = row.get("requested_by_agent")
    thread_id = row.get("thread_id")
    if not agent_slug or not thread_id:
        print(
            f"[channel_dispatch] approval row missing agent/thread: {row!r}",
            flush=True,
        )
        return

    # 2. Resolve the org-scoped agent row id once (used for sender_agent_id
    # on the messages we'll post). Missing agent row is recoverable —
    # we'll post with sender_agent_id=None as a defensive fallback.
    agent_row_id = _resolve_agent_id(supabase, org_id=org_id, slug=agent_slug)

    # 3. Drain the resume stream. The orchestrator updates the approval
    # row status internally, so by the end of this call the original
    # `approvals.status` is "approved" or "rejected" already.
    if decision == "approved":
        gen = stream_resume_approved(
            approval_id=approval_id, reviewer_user_id=user_id,
        )
    else:
        gen = stream_resume_rejected(
            approval_id=approval_id, reviewer_user_id=user_id, feedback=feedback,
        )

    drained = with_tool_context(
        gen, org_id=org_id, user_id=user_id, supabase=supabase,
    )
    try:
        async for _event in drained:
            pass
    except Exception as e:
        print(f"[channel_dispatch] resume run failed: {e!r}", flush=True)
        _post_channel_message(
            supabase,
            channel_id=channel_id,
            org_id=org_id,
            sender_agent_id=agent_row_id,
            body=f"@{agent_slug} hit an error and couldn't respond.",
            in_reply_to_message_id=triggering_message_id,
        )
        return

    # 4. Post the next channel message — text response if the run
    # completed, fresh approval card if it paused at another gate.
    await _post_agent_result(
        supabase,
        agent_slug=agent_slug,
        agent_row_id=agent_row_id or "",
        thread_id=thread_id,
        channel_id=channel_id,
        org_id=org_id,
        triggering_message_id=triggering_message_id,
    )


def run_resume_to_channel_safely(
    *,
    approval_id: str,
    decision: str,
    feedback: str | None,
    channel_id: str,
    org_id: str,
    user_id: str,
    triggering_message_id: str,
    supabase,
) -> None:
    """Sync wrapper for the BackgroundTasks scheduler — same shape as
    `run_dispatch_safely` so the channels router can call either with
    minimal ceremony."""
    import asyncio

    try:
        asyncio.run(
            dispatch_resume_to_channel(
                approval_id=approval_id,
                decision=decision,
                feedback=feedback,
                channel_id=channel_id,
                org_id=org_id,
                user_id=user_id,
                triggering_message_id=triggering_message_id,
                supabase=supabase,
            )
        )
    except Exception as e:
        print(f"[channel_dispatch] resume failed: {e!r}", flush=True)


def run_dispatch_safely(
    *,
    agent_slug: str,
    channel_id: str,
    org_id: str,
    user_id: str,
    triggering_message_id: str,
    triggering_message_body: str,
    supabase,
) -> None:
    """Sync wrapper used by FastAPI BackgroundTasks.

    BackgroundTasks accepts both sync and async callables but swallows
    any exception silently. We catch + log + post a fallback so the
    channel never goes quiet.
    """
    import asyncio

    try:
        asyncio.run(
            dispatch_agent_to_channel(
                agent_slug=agent_slug,
                channel_id=channel_id,
                org_id=org_id,
                user_id=user_id,
                triggering_message_id=triggering_message_id,
                triggering_message_body=triggering_message_body,
                supabase=supabase,
            )
        )
    except Exception as e:
        print(f"[channel_dispatch] failed: {e!r}", flush=True)
        try:
            _post_channel_message(
                supabase,
                channel_id=channel_id,
                org_id=org_id,
                sender_agent_id=None,
                body=f"@{agent_slug} hit an error and couldn't respond.",
                in_reply_to_message_id=triggering_message_id,
            )
        except Exception as e2:
            print(f"[channel_dispatch] fallback post failed: {e2!r}", flush=True)
