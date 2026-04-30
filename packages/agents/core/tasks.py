"""
Agent-spawned tasks — shared helper for any agent that wants to drop work
into the user's `/app/tasks` workspace.

When the Strategist generates a weekly brief, each ranked idea becomes a
To-Do task. When the Brand Manager pitches a sponsor, a "follow up next
Tuesday" task can be queued. When the Community Manager flags a VIP
comment, a "reply to <commenter>" task lands in the inbox. All of those
flows route through this module — keeps the schema knowledge (tasks
table columns, how `agents.id` is resolved from a slug) in one place.

Best-effort by design: every helper here swallows DB errors silently.
A failed task insert is far less bad than a failed agent run; the
agent's primary work (sending the email, generating the brief, etc.)
already succeeded by the time we land here. Future improvements could
emit a system notification when a spawn fails, but that's polish.
"""
from __future__ import annotations

import uuid
from typing import Any

from packages.integrations.context import current_supabase


def _is_real_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _resolve_agent_id(supabase: Any, org_id: str, agent_slug: str) -> str | None:
    """Look up the `agents.id` for a slug within the org. Cached lookups
    aren't worth it yet — agents create at most a handful of tasks per
    run, and the DB call is local. Returns None if the slug isn't
    registered for the org (system agents may not have a row); the
    caller's task still inserts cleanly without `agent_id`."""
    try:
        result = (
            supabase.table("agents")
            .select("id")
            .eq("org_id", org_id)
            .eq("slug", agent_slug)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    if result.data:
        return result.data[0].get("id")
    return None


async def create_task_from_agent(
    *,
    org_id: str | None,
    agent_slug: str,
    title: str,
    description: str | None = None,
    priority: str = "medium",
    status: str = "todo",
    deal_id: str | None = None,
    due_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Insert a single task on behalf of an agent.

    Returns the new task id, or None when the write was skipped
    (no Supabase, dev org, blank title) or failed.

    `agent_slug` is mapped to `tasks.agent_id` via a quick lookup —
    keeps the call sites slug-friendly so each agent doesn't have to
    cache its own UUID. If the slug isn't registered, the task still
    gets inserted with `agent_id = NULL`.

    `metadata` rides on the `tasks.metadata` jsonb column (existing) —
    use it to back-link to the source artifact (e.g.
    `{"brief_id": "...", "idea_index": 2}` so a future "show source"
    feature can navigate from a task back to the brief that spawned it).
    """
    supabase = current_supabase.get()
    if (
        not _is_real_uuid(org_id)
        or supabase is None
        or not (title or "").strip()
    ):
        return None

    agent_id = _resolve_agent_id(supabase, org_id, agent_slug)

    payload: dict[str, Any] = {
        "org_id": org_id,
        "title": title.strip()[:300],
        "description": description,
        "status": status,
        "priority": priority,
        "agent_id": agent_id,
        "deal_id": deal_id if _is_real_uuid(deal_id) else None,
        "due_at": due_at,
        "metadata": metadata or {},
        # `created_by` is intentionally null — agent-spawned tasks aren't
        # owned by any specific user. The dashboard can render an
        # agent-name badge when `agent_id` is set.
    }
    try:
        result = supabase.table("tasks").insert(payload).execute()
    except Exception as e:
        print(f"[tasks] create_task_from_agent failed: {e!r}", flush=True)
        return None
    if result.data:
        return result.data[0].get("id")
    return None


async def create_tasks_from_agent(
    *,
    org_id: str | None,
    agent_slug: str,
    items: list[dict[str, Any]],
) -> list[str]:
    """Bulk variant — used when an agent has multiple tasks to drop in
    one go (e.g. Strategist's brief produces N ideas → N tasks). Each
    item is passed to `create_task_from_agent`. Returns the list of
    successfully-created task ids in input order; failures are skipped
    (no exception) so a single bad row doesn't cancel the rest.

    The implementation calls `create_task_from_agent` once per item rather
    than batching the insert — keeps error handling simple and lets each
    item's `metadata` dict be preserved exactly. At the volumes agents
    operate (~5 ideas per brief) this is fine; a future bulk insert
    optimization is justifiable when an agent needs to spawn 50+ at once.
    """
    ids: list[str] = []
    for item in items:
        new_id = await create_task_from_agent(
            org_id=org_id,
            agent_slug=agent_slug,
            **item,
        )
        if new_id:
            ids.append(new_id)
    return ids
