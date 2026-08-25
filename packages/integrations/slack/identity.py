"""Slack user → Marcus user resolver.

When the Events API delivers a message.groups event, we know which Slack
workspace it came from (`team_id`) and which Slack user wrote it
(`event.user`), but neither tells us *which Marcus user* should be billed
for the run, scope the agent's tools to the right org, or sign tool writes.

Email match is the simplest bridge: Slack workspaces tend to have everyone
on their work email, and Marcus signups are email-based, so 95% of the
time the same person on both sides has the same email. Where it fails (a
Slack workspace member who hasn't signed up to Marcus, or signed up under
a different email), we surface a clear "link your account" message in the
Slack thread instead of silently routing to a wrong user.

Future Phase B+: per-user OAuth subflow so each Slack member individually
links their Marcus account, no email match required.
"""
from __future__ import annotations

from typing import Any

from packages.integrations.slack import client as slack_client


async def resolve_marcus_user(
    *,
    supabase: Any,
    slack_team_id: str,
    slack_user_id: str,
    slack_bot_token: str,
    known_org_id: str | None = None,
) -> dict | None:
    """Resolve a Slack user to a Marcus (org_id, user_id) pair.

    Returns {"org_id": str, "user_id": str, "email": str} on success, or
    None if any step fails (no email visible, no Marcus user with that
    email, the matched user isn't a member of the org connected to this
    Slack workspace, etc).

    Steps:
      1. Slack `users.info` → email (requires users:read.email scope).
      2. Marcus `users` table lookup by email (case-insensitive).
      3. `integrations` lookup: which org has this Slack team_id installed?
      4. `org_members` confirms the matched user is in that org.

    Each step is failure-tolerant — missing data returns None, never
    raises. The caller decides what message to surface in Slack.
    """
    email = await slack_client.lookup_user_email(slack_bot_token, slack_user_id)
    if not email:
        return None

    user_resp = (
        supabase.table("users")
        .select("id, email")
        .ilike("email", email)
        .limit(1)
        .execute()
    )
    if not user_resp.data:
        return None
    user_id = user_resp.data[0]["id"]

    # Find the org that installed this Slack workspace. Callers that already
    # looked the install up (slack_runner does, two steps earlier) pass
    # known_org_id and skip this duplicate round-trip. integrations.metadata
    # is jsonb; postgrest's `->>team_id` operator extracts as text.
    if known_org_id:
        org_id = known_org_id
    else:
        integ_resp = (
            supabase.table("integrations")
            .select("org_id, metadata")
            .eq("provider", "slack")
            .filter("metadata->>team_id", "eq", slack_team_id)
            .limit(1)
            .execute()
        )
        if not integ_resp.data:
            return None
        org_id = integ_resp.data[0]["org_id"]

    # Confirm the user is a member of that org. If not, the email matched
    # someone in a different workspace and we should NOT route here.
    member_resp = (
        supabase.table("org_members")
        .select("user_id")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not member_resp.data:
        return None

    return {"org_id": org_id, "user_id": user_id, "email": email}
