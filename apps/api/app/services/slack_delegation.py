"""
Delegated agent runs over Slack — the execution half of `delegate_task`.

When the DM front door (Image Reader) delegates work during a Slack run,
`slack_runner.handle_message` drains the queued delegations (see
packages/agents/core/delegation.py) and calls `spawn_delegated_run` for
each: the target agent runs as a tracked background task on the SAME
Slack thread, under its own persona, on its OWN Marcus thread — the
thread_id is the LangGraph checkpointer key, and two graphs must never
share one (slack_runner._resolve_marcus_thread keys by agent slug for
exactly this reason).

Reuses slack_runner's private helpers rather than duplicating them; the
module boundary is file size and ownership (same split rationale as
scheduler.py / content_dispatch.py), not behavior. Because the delegated
run goes through `_run_and_post`, a delegated agent that pauses at an
approval gate posts its approval card into the DM thread and resumes via
the normal interactive handler — approvals work in the DM for free.

Failures never vanish: if a delegated run raises, a short note is posted
to the thread under the agent's persona, so "handed to broll" is never
silently followed by nothing.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.auth import with_tool_context
from app.services.graph_orchestrator import stream_new_run
from app.services.slack_runner import (
    _ensure_thread,
    _insert_message,
    _resolve_marcus_thread,
    _run_and_post,
)
from packages.integrations.slack import client as slack_client
from packages.integrations.slack.oauth import persona_for

# Strong refs to in-flight delegated runs (asyncio only keeps weak refs;
# a rendering b-roll batch legitimately runs for minutes and must not be
# garbage-collected mid-flight).
_delegated_tasks: set[asyncio.Task] = set()

# Bound CONCURRENT delegated graph runs process-wide. Each is a full LLM
# run (possibly burning paid render credits); the events webhook has no
# per-user throttle, so without this a burst of DMs fans out unbounded.
# Excess delegations queue here rather than being dropped.
_delegation_sem = asyncio.Semaphore(6)

# One delegated run at a time per (channel, root_ts, slug): a second
# delegation to the same agent on the same Slack thread (e.g. two quick
# DMs) would resolve the SAME Marcus thread and race one checkpointer
# lineage. Same-message duplicates are already coalesced upstream; this
# serializes cross-message overlap.
_thread_locks: dict[tuple, asyncio.Lock] = {}


def _lock_for(key: tuple) -> asyncio.Lock:
    lock = _thread_locks.get(key)
    if lock is None:
        # Opportunistic prune so the dict can't grow unbounded over months.
        if len(_thread_locks) > 512:
            for k in [k for k, v in _thread_locks.items() if not v.locked()][:256]:
                _thread_locks.pop(k, None)
        lock = asyncio.Lock()
        _thread_locks[key] = lock
    return lock


def spawn_delegated_run(
    *,
    supabase: Any,
    org_id: str,
    user_id: str,
    bot_token: str,
    scopes: list,
    slack_team_id: str,
    slack_channel_id: str,
    root_ts: str,
    agent_slug: str,
    instruction: str,
) -> None:
    """Fire one delegated agent run as a tracked background task."""
    task = asyncio.create_task(
        _run_delegated_agent(
            supabase=supabase,
            org_id=org_id,
            user_id=user_id,
            bot_token=bot_token,
            scopes=scopes,
            slack_team_id=slack_team_id,
            slack_channel_id=slack_channel_id,
            root_ts=root_ts,
            agent_slug=agent_slug,
            instruction=instruction,
        )
    )
    _delegated_tasks.add(task)
    task.add_done_callback(_delegated_tasks.discard)


async def _run_delegated_agent(
    *,
    supabase: Any,
    org_id: str,
    user_id: str,
    bot_token: str,
    scopes: list,
    slack_team_id: str,
    slack_channel_id: str,
    root_ts: str,
    agent_slug: str,
    instruction: str,
) -> None:
    """Run the delegated agent and post its reply into the Slack thread.

    Mirrors the tail of slack_runner.handle_message: own Marcus thread
    (keyed by this agent's slug on the same Slack thread), user turn
    persisted with delegation provenance, orchestrator stream drained by
    `_run_and_post` under the delegated agent's persona.
    """
    persona = persona_for(agent_slug, scopes)
    # `ran` flips once the orchestrator stream has been fully drained — at
    # that point the specialist's work (and any side effects) COMPLETED and
    # only delivering the reply can still fail; the failure note must not
    # tell the user to re-run completed work (double spend).
    ran = False
    try:
        async with _delegation_sem, _lock_for(
            (slack_channel_id, root_ts, agent_slug)
        ):
            # Sync supabase-py round-trips — run off-loop so a burst of
            # delegated runs can't stall the event loop (a stalled loop
            # delays webhook acks past Slack's 3s window → retries).
            marcus_thread_id = await asyncio.to_thread(
                _resolve_marcus_thread,
                supabase,
                org_id=org_id,
                agent_slug=agent_slug,
                slack_team_id=slack_team_id,
                slack_channel_id=slack_channel_id,
                slack_thread_root_ts=root_ts,
            )
            await asyncio.to_thread(
                _ensure_thread,
                supabase,
                thread_id=marcus_thread_id,
                org_id=org_id,
                user_id=user_id,
                title=f"#backroom-{agent_slug} (Slack)",
            )
            # The delegated agent sees a normal user request with relay
            # provenance. The instruction is LLM-composed and may embed
            # content from screenshots/voice notes — queue_delegation
            # flattened its whitespace so it can't forge message structure.
            message = f"(Relayed by the front door from the creator's Slack DM) {instruction}"
            await asyncio.to_thread(
                _insert_message,
                supabase,
                thread_id=marcus_thread_id,
                role="user",
                content=message,
                metadata={
                    "source": "slack",
                    "delegated_by": "image-reader",
                    "slack_channel_id": slack_channel_id,
                },
            )
            stream = with_tool_context(
                stream_new_run(
                    agent_slug=agent_slug,
                    message=message,
                    thread_id=marcus_thread_id,
                    org_id=org_id,
                    user_id=user_id,
                ),
                org_id=org_id,
                user_id=user_id,
                supabase=supabase,
            )
            try:
                await _run_and_post(
                    stream=stream,
                    supabase=supabase,
                    bot_token=bot_token,
                    slack_channel_id=slack_channel_id,
                    root_ts=root_ts,
                    persona=persona,
                    marcus_thread_id=marcus_thread_id,
                )
            finally:
                # _run_and_post only raises from the Slack posts at its
                # tail — the graph itself surfaces failures as SSE error
                # events. Reaching here at all means the run executed.
                ran = True
    except Exception as e:  # noqa: BLE001 — a delegated run must never die silently
        print(f"[slack_delegation] {agent_slug} run failed (ran={ran}): {e!r}", flush=True)
        note = (
            (
                f"⚠️ The delegated work finished, but I couldn't deliver the "
                f"reply here ({str(e)[:150]}). Check the agent's channel or "
                f"the workspace before asking again — re-running may repeat "
                f"completed work."
            )
            if ran
            else (
                f"⚠️ I couldn't start that delegated task ({str(e)[:150]}). "
                f"Try asking me again, or talk to the agent directly in its "
                f"channel."
            )
        )
        try:
            await slack_client.post_message_in_thread(
                bot_token,
                slack_channel_id,
                note,
                thread_ts=root_ts,
                **persona,
            )
        except Exception as post_err:
            print(
                f"[slack_delegation] failure note post failed: {post_err!r}",
                flush=True,
            )
