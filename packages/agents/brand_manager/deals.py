"""
Brand Manager deal-pipeline persistence.

Two responsibilities:

  - `log_deal_pitched(...)` — called from `_send_email_node` after the Gmail
    API confirms an approved pitch went out. Writes a `brand_deals` row with
    stage='pitched'. Best-effort; failures don't break the user-facing
    reply (the email already left the building either way).

  - `list_active_deals(org_id, supabase=None, limit=10)` — read the
    pipeline. Used by both the LLM-facing `list_active_deals_tool`
    (which reads `current_supabase` from ContextVars) and the
    cross-agent `peer_context` loader (which gets supabase passed in
    explicitly). Never raises — returns `[]` on misconfig / DB errors
    so peer agents can render a brief even when the pipeline is
    inaccessible.
"""
from __future__ import annotations

import re
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


# `send_pitch_email` returns "Sent. Gmail message id: <id>" on success — capture
# the id for later "did this email bounce / open" features without needing to
# refactor the tool's return shape. The column `external_message_id` stays
# provider-agnostic so a future custom-domain sender (Resend / SES) can reuse it.
_MESSAGE_ID_RE = re.compile(r"(?:Gmail|Resend)\s+message\s+id:\s*(\S+)", re.IGNORECASE)


def _extract_message_id(send_result: str | None) -> str | None:
    if not send_result:
        return None
    m = _MESSAGE_ID_RE.search(send_result)
    return m.group(1) if m else None


async def log_deal_pitched(
    *,
    org_id: str | None,
    thread_id: str | None,
    brand_name: str,
    recipient: str | None,
    subject: str | None,
    send_result: str | None,
) -> str | None:
    """Insert a `brand_deals` row recording a just-sent pitch.

    No-op when:
      - Supabase isn't configured (local dev path)
      - org_id isn't a real UUID (dev fallback "dev")
      - The brand_name is empty (defensive — caller should always pass one)

    Errors during insert are swallowed and logged; we never want pipeline
    bookkeeping to bring down a successful send.

    Returns the inserted row's `id`, or `None` if the write was skipped.
    """
    supabase = current_supabase.get()
    if not _is_real_uuid(org_id) or supabase is None or not (brand_name or "").strip():
        return None

    payload = {
        "org_id": org_id,
        "thread_id": thread_id if _is_real_uuid(thread_id) else None,
        "brand_name": brand_name.strip()[:200],
        "recipient": recipient,
        "subject": subject,
        "stage": "pitched",
        "external_message_id": _extract_message_id(send_result),
    }
    try:
        result = supabase.table("brand_deals").insert(payload).execute()
        if result.data:
            return result.data[0].get("id")
    except Exception as e:
        print(f"[brand_deals] insert failed: {e!r}", flush=True)
    return None


async def list_active_deals(
    *,
    org_id: str | None,
    supabase: Any = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the most recent `brand_deals` rows for `org_id`.

    `supabase` defaults to the request-scoped client from `current_supabase`
    when omitted — keeps the LLM-tool call site terse — but accepts an
    explicit client for non-request code paths (peer_context loader,
    background jobs, tests).

    Returns `[]` on any failure: missing supabase, dev org, table missing,
    DB error. Callers render an empty pipeline rather than seeing a stack
    trace.
    """
    if supabase is None:
        supabase = current_supabase.get()
    if not _is_real_uuid(org_id) or supabase is None:
        return []

    try:
        result = (
            supabase.table("brand_deals")
            .select("id, brand_name, recipient, subject, stage, "
                    "pitched_at, last_updated_at, external_message_id")
            .eq("org_id", org_id)
            .order("last_updated_at", desc=True)
            .limit(max(1, min(limit, 50)))
            .execute()
        )
        return list(result.data or [])
    except Exception:
        return []
