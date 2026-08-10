"""
Resend transactional email — the agents' ad-hoc send path.

apps/api/app/services/email.py owns the product's invite mailer (FastAPI
Settings-bound, HTML-templated). This is the packages-layer equivalent for
agent tools — "email this to my contractor, CC me" from Slack chat — using
the same Resend account and the same env: RESEND_API_KEY + EMAIL_FROM.
Plain-text only: the tool sends exactly the words the creator dictated.

KEY-GATED + GRACEFUL DEGRADATION: is_configured() is False until both env
vars are set; send_email raises ResendUnavailable then, and the calling
tool reports "not configured" instead of failing the run.
"""
from __future__ import annotations

import os

import httpx

RESEND_API_URL = "https://api.resend.com/emails"


class ResendError(RuntimeError):
    """A Resend send failed (HTTP error, network failure)."""


class ResendUnavailable(ResendError):
    """Resend is not configured (RESEND_API_KEY / EMAIL_FROM missing)."""


def is_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY") and os.environ.get("EMAIL_FROM"))


def _strip_header_newlines(value: str) -> str:
    """RFC 5322 forbids CR/LF in header fields; strip them so nothing that
    reaches the subject line can smuggle extra headers."""
    return (value or "").replace("\r", " ").replace("\n", " ").strip()


async def send_email(
    *,
    to: list[str],
    subject: str,
    text: str,
    cc: list[str] | None = None,
) -> str:
    """Send a plain-text email through Resend; return the message id.

    Raises ResendUnavailable when the env pair is missing, ResendError on
    network failure or a non-2xx Resend response (message truncated —
    Resend can echo user-supplied content back in errors).
    """
    api_key = os.environ.get("RESEND_API_KEY")
    sender = os.environ.get("EMAIL_FROM")
    if not api_key or not sender:
        raise ResendUnavailable(
            "RESEND_API_KEY / EMAIL_FROM not set — email sending is not configured."
        )

    payload: dict = {
        "from": sender,
        "to": list(to),
        "subject": _strip_header_newlines(subject),
        "text": text,
    }
    if cc:
        payload["cc"] = list(cc)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as e:
        raise ResendError(f"network error: {e}") from e

    if resp.status_code >= 400:
        try:
            err = resp.json()
            msg = err.get("message") or err.get("name") or resp.text
        except Exception:
            msg = resp.text or f"HTTP {resp.status_code}"
        msg = (msg or "")[:200].replace("\r", " ").replace("\n", " ").strip()
        raise ResendError(f"resend {resp.status_code}: {msg}")

    body = resp.json() or {}
    return body.get("id") or ""
