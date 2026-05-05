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
from app.services.graph_orchestrator import _compile_agent, stream_new_run
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
) -> None:
    """Insert a `channel_messages` row authored by an agent.

    Bypasses the user-side mention parser entirely — agent-authored
    messages must never re-trigger dispatch (would loop forever on
    e.g. `@publisher` quoting a user's prompt back).
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
    }
    try:
        supabase.table("channel_messages").insert(payload).execute()
    except Exception as e:
        print(f"[channel_dispatch] post failed: {e!r}", flush=True)


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

    # 4. Inspect final state. If `state.next` is non-empty the run paused
    # at an interrupt (approval gate) — surface that to the channel.
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

    # 5. Pull the last AIMessage with non-empty content from state.values.
    messages = (state.values or {}).get("messages", [])
    final_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, list):
                # Claude content-block list — flatten to text blocks only.
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
