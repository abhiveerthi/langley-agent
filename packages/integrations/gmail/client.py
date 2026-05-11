"""
Connection persistence + access-token refresh for Gmail. Mirrors the
YouTube client almost exactly — the difference is the provider key
('gmail') and what gets stashed in `metadata` (the connected email
address rather than a YouTube channel).

`get_fresh_access_token` is the only function any future agent code
needs to call — it auto-refreshes when the stored access token is
within 2 minutes of expiry.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from supabase import Client

from packages.integrations.gmail.oauth import OAuthTokens, refresh_access_token

PROVIDER = "gmail"
REFRESH_SKEW_SECONDS = 120


def _expires_at(expires_in: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()


def get_connection(supabase: Client, org_id: str) -> dict | None:
    resp = (
        supabase.table("integrations")
        .select("*")
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def save_connection(
    supabase: Client,
    org_id: str,
    tokens: OAuthTokens,
    userinfo: dict,
) -> dict:
    row = {
        "org_id": org_id,
        "provider": PROVIDER,
        "status": "active",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_expires_at": _expires_at(tokens.expires_in),
        "scopes": tokens.scope.split() if tokens.scope else [],
        "metadata": userinfo,  # email, name, picture, verified_email
    }
    resp = (
        supabase.table("integrations")
        .upsert(row, on_conflict="org_id,provider")
        .execute()
    )
    return resp.data[0]


def delete_connection(supabase: Client, org_id: str) -> None:
    (
        supabase.table("integrations")
        .delete()
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )


async def get_fresh_access_token(
    supabase: Client,
    org_id: str,
    client_id: str,
    client_secret: str,
) -> str:
    """Return a non-expired access token, refreshing if needed.

    Raises if the org isn't connected or the refresh token is missing
    (which happens when a user revokes access in their Google Account —
    the refresh column on the row is wiped). Caller should surface
    'reconnect Gmail' to the user.
    """
    conn = get_connection(supabase, org_id)
    if not conn:
        raise RuntimeError("Gmail is not connected for this org")

    expires_at_iso = conn.get("token_expires_at")
    expired = True
    if expires_at_iso:
        expires_dt = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
        expired = expires_dt.timestamp() - time.time() < REFRESH_SKEW_SECONDS

    if not expired:
        return conn["access_token"]

    if not conn.get("refresh_token"):
        raise RuntimeError("No Gmail refresh token on file; reconnect Gmail")

    tokens = await refresh_access_token(conn["refresh_token"], client_id, client_secret)
    (
        supabase.table("integrations")
        .update(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_expires_at": _expires_at(tokens.expires_in),
                "scopes": tokens.scope.split() if tokens.scope else conn.get("scopes", []),
                "status": "active",
            }
        )
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )
    return tokens.access_token


def mark_connection_error(supabase: Client, org_id: str, error: str) -> None:
    (
        supabase.table("integrations")
        .update({"status": "error", "metadata": {"last_error": error}})
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )


# ── Outgoing message send ─────────────────────────────────────────────────
# Gmail's `users.messages.send` takes a single field: a base64url-encoded
# RFC 2822 message. Plain text only here; multipart/alternative + HTML can
# slot in later if newsletter formatting outgrows plain.
import base64
from email.message import EmailMessage

import httpx

GMAIL_SEND_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _build_rfc2822(
    *,
    to: str,
    subject: str,
    body_text: str,
    from_email: str,
    from_name: str | None = None,
    reply_to: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        # Bcc on the EmailMessage is honored by Gmail when sent via the API
        # (it strips the header before delivery, same as a normal MUA).
        msg["Bcc"] = ", ".join(bcc)
    msg.set_content(body_text)
    return bytes(msg)


async def send_message(
    access_token: str,
    *,
    to: str,
    subject: str,
    body_text: str,
    from_email: str,
    from_name: str | None = None,
    reply_to: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict:
    """Send a plain-text email via Gmail's REST API.

    Returns the parsed JSON body of the send response — at minimum
    `{"id": "<gmail message id>", "threadId": "...", "labelIds": [...]}`.
    Raises `RuntimeError` on any non-2xx so callers can surface the
    error string to the user.
    """
    raw = _build_rfc2822(
        to=to,
        subject=subject,
        body_text=body_text,
        from_email=from_email,
        from_name=from_name,
        reply_to=reply_to,
        cc=cc,
        bcc=bcc,
    )
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            GMAIL_SEND_ENDPOINT,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": encoded},
        )

    if resp.status_code >= 400:
        # Gmail returns structured errors in `error.message`. Surface the
        # whole body for diagnostics; the agent layer trims for UI.
        raise RuntimeError(
            f"Gmail send failed ({resp.status_code}): {resp.text[:500]}"
        )
    return resp.json()
