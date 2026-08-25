"""
Live delegation queue — how the DM front door's `delegate_task` actually
RUNS the target agent instead of just filing a note.

The Slack runner activates a collector around each agent run. When the
Image Reader's delegate_task tool fires inside that run, it queues the
delegation here; after the front door's own reply is posted, the runner
drains the queue and dispatches each target agent over the SAME Slack
thread — each on its own Marcus thread, because a thread_id is also the
LangGraph checkpointer key and two graphs must never share one. The
specialist's reply (or its approval card) lands right in the DM.

Without an active collector (web chat, direct API runs), delegate_task
keeps its original behavior: file a workspace task on the board.

ContextVar mechanics this relies on (same as current_supabase et al.):
generators don't get their own context, so the collector set in the
runner's task context is visible to tool calls made while the stream is
being drained; any tasks LangGraph spawns internally snapshot that
context at creation. The queue is a shared LIST — appends mutate the one
object the runner holds a direct reference to, so no cross-context
read-back is needed.
"""
from __future__ import annotations

from contextvars import ContextVar, Token

# Matches the front door's per-message tool-call cap — an injected
# "delegate 50 tasks" must not fan out into 50 agent runs.
MAX_DELEGATIONS_PER_RUN = 3

# Bound the instruction so a pathological tool call can't push megabytes
# into the delegated agent's opening message.
MAX_INSTRUCTION_CHARS = 4000

_pending: ContextVar[list[dict] | None] = ContextVar(
    "pending_delegations", default=None
)


def activate_collector() -> tuple[list[dict], Token]:
    """Arm the queue for the current context. Returns (queue, token) —
    the caller keeps the queue reference to drain after the run and MUST
    reset with `deactivate_collector(token)` when done."""
    queue: list[dict] = []
    token = _pending.set(queue)
    return queue, token


def deactivate_collector(token: Token) -> None:
    _pending.reset(token)


def collector_active() -> bool:
    """True when a live dispatcher armed the queue (i.e. delegation will
    actually run the agent rather than file a board task)."""
    return _pending.get() is not None


def queue_delegation(agent_slug: str, instruction: str) -> bool:
    """Queue one delegation for post-run dispatch. False when no collector
    is active or the per-run cap is already reached — the caller decides
    what to tell the model in each case."""
    queue = _pending.get()
    if queue is None:
        return False
    if len(queue) >= MAX_DELEGATIONS_PER_RUN:
        return False
    # Collapse all whitespace runs (incl. newlines) to single spaces: the
    # instruction is LLM-composed from external input (screenshots, voice
    # transcripts), and newlines are how forged "SYSTEM NOTE:" structure or
    # a fake provenance prefix would smuggle itself into the delegated
    # agent's opening message.
    instruction = " ".join((instruction or "").split())[:MAX_INSTRUCTION_CHARS]
    queue.append({"agent_slug": agent_slug, "instruction": instruction})
    return True
