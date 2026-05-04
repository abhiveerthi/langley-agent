"""
Slack delivery for org invites.

Wraps the existing per-org Slack bot (stored in the `integrations` table)
to post an invite link to an owner-chosen channel. The bot can post into
channels it's been added to but cannot DM users — the inviter picks the
channel they want the invite posted to.

Channel listing for the picker UI lives in routers/slack_meta.py and
calls `conversations.list` with a 5-min cache.
"""
from __future__ import annotations

import httpx
from supabase import Client

from packages.integrations.slack import client as slack_client


class SlackDeliveryError(RuntimeError):
    """Raised when Slack returns ok=false or an HTTP error. The caller
    stamps the message on org_invites.last_delivery_error."""


def _escape_mrkdwn(s: str) -> str:
    """Strip Slack mrkdwn link/control characters from owner-controlled
    fields. `<...|...>` is Slack's link syntax — without escaping these,
    a malicious org_name like `<https://phish/|Backroom>` would render
    as a clickable link to an attacker domain. Slack also reserves `&`
    for HTML entities."""
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "&#124;")
    )


def _format_invite_message(
    *, magic_link: str, invitee_email: str, inviter_name: str, org_name: str
) -> str:
    safe_inviter = _escape_mrkdwn(inviter_name)
    safe_invitee = _escape_mrkdwn(invitee_email)
    safe_org = _escape_mrkdwn(org_name)
    # Slack's chat.postMessage uses mrkdwn by default. The magic link
    # itself goes inside the link syntax `<URL|label>` — only Supabase-
    # generated URLs land in this slot, so we don't escape it (escaping
    # would break the URL). Belt-and-suspenders: also reject any link
    # that doesn't start with http/https.
    if not (magic_link.startswith("http://") or magic_link.startswith("https://")):
        magic_link = ""
    return (
        f"*{safe_inviter}* invited *{safe_invitee}* to the *{safe_org}* "
        f"workspace on Backroom.\n"
        f"<{magic_link}|Click here to set up your account and join>."
    )


async def post_invite_to_slack(
    *,
    supabase: Client,
    org_id: str,
    channel_id: str,
    magic_link: str,
    invitee_email: str,
    inviter_name: str,
    org_name: str,
) -> str:
    """Post the invite to a Slack channel. Returns the message ts on
    success; raises SlackDeliveryError on any failure.
    """
    conn = slack_client.get_connection(supabase, org_id)
    if not conn:
        raise SlackDeliveryError("Slack integration not installed for this org")

    access_token = conn.get("access_token")
    if not access_token:
        raise SlackDeliveryError("Slack access_token missing on integration row")

    text = _format_invite_message(
        magic_link=magic_link,
        invitee_email=invitee_email,
        inviter_name=inviter_name,
        org_name=org_name,
    )

    try:
        resp = await slack_client.post_message(access_token, channel_id, text)
    except httpx.HTTPError as e:
        raise SlackDeliveryError(f"network: {e}") from e
    except Exception as e:
        raise SlackDeliveryError(str(e)) from e

    if not resp.get("ok"):
        raise SlackDeliveryError(f"slack: {resp.get('error', 'unknown')}")

    return resp.get("ts", "")
