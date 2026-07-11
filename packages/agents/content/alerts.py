"""
Failure escalation — straight to the owner's Slack.

Product requirement: when a dependency (Riverside, Opus, YouTube, Monday…)
breaks, the alert goes to BRADEN, not Kaydi — he monitors Slack (watch +
phone) and can fix credentials/outages himself. Kaydi's surface is the
Monday board; operational noise doesn't belong there.

Channel comes from agents.config `escalation_slack_channel_id` (set once
via PATCH /api/agents/content/config). Best-effort like every side
channel: no Slack connection, no channel configured, or a send failure
just logs — an alert about a failure must never cause another failure.
"""
from __future__ import annotations

import logging
from typing import Any

from packages.agents.core.monday_tasks import _is_real_uuid
from packages.agents.content.tools import load_agent_config
from packages.integrations.context import current_supabase

log = logging.getLogger("content.alerts")


async def escalate(org_id: str, message: str, *, supabase: Any = None) -> bool:
    """Send one failure alert to the configured escalation channel.

    `supabase` may be passed explicitly by callers running outside a
    request/run context (the scheduler's stuck-check); defaults to the
    ContextVar client. Returns True iff the Slack post went out.
    """
    supabase = supabase if supabase is not None else current_supabase.get()
    if supabase is None or not _is_real_uuid(org_id):
        return False

    try:
        # load_agent_config reads via the ContextVar — do a direct read so
        # explicit-client callers work too.
        resp = (
            supabase.table("agents")
            .select("config")
            .eq("org_id", org_id)
            .eq("slug", "content")
            .limit(1)
            .execute()
        )
        config = (resp.data[0].get("config") if resp.data else None) or {}
    except Exception:
        config = {}
    channel = (config.get("escalation_slack_channel_id") or "").strip()
    if not channel:
        return False

    try:
        from packages.integrations.slack import client as slack_client

        conn = slack_client.get_connection(supabase, org_id)
        token = (conn or {}).get("access_token")
        if not token or (conn or {}).get("status") == "error":
            return False
        await slack_client.post_message(
            token, channel, f":rotating_light: Content Agent: {message[:2800]}"
        )
        return True
    except Exception as e:
        log.warning("escalation send failed for org=%s: %r", org_id, e)
        return False
