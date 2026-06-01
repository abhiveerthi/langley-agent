"""
B-Roll Producer tools + Dropbox foldering helper.

`get_broll_tools()` returns the LLM-callable tools — here a single
`generate_broll_clip` tool that submits one prompt to Higgsfield and returns a
status/URL. It degrades gracefully: with no HIGGSFIELD_API_KEY the underlying
client raises HiggsfieldUnavailable, which we catch and return as a clear
"not configured" status string rather than crashing the run.

`deposit_clip_to_dropbox` is NOT an LLM tool — it's a helper the
`organize_dropbox` graph node calls to file rendered clips into a dated,
topic-organized folder. It reuses the org-Dropbox connection-resolution pattern
from packages/agents/core/pdf_export.py (get_connection + get_fresh_access_token
+ upload_file), staying best-effort: a delivery hiccup never breaks the chat
reply.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from langchain_core.tools import tool

from packages.integrations.context import current_supabase


# ── Dropbox foldering ───────────────────────────────────────────────────────
# Clips live under /B-Roll/<date>/<topic>/ so the creator finds them organized
# by shoot day and subject, e.g. /B-Roll/2026-06-15/Conservative-Commentary/.
_BROLL_ROOT = "/B-Roll"
_SAFE = re.compile(r"[^a-zA-Z0-9._-]")


def _safe_segment(name: str, fallback: str) -> str:
    """Collapse a free-text label into one safe path segment.

    Spaces → hyphens, then anything outside [A-Za-z0-9._-] → '_', so an
    LLM/user-supplied topic can never escape its folder or inject separators.
    """
    cleaned = (name or "").strip().replace(" ", "-")
    cleaned = _SAFE.sub("_", cleaned)
    return cleaned or fallback


def broll_folder_path(topic: str, *, date: str | None = None) -> str:
    """Build the dated, topic-organized Dropbox folder for a clip.

    date defaults to today's UTC date (YYYY-MM-DD). topic is slugified.
    """
    day = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_seg = _safe_segment(day, "undated")
    topic_seg = _safe_segment(topic, "misc")
    return f"{_BROLL_ROOT}/{day_seg}/{topic_seg}"


async def deposit_clip_to_dropbox(
    org_id: str,
    *,
    filename: str,
    clip_bytes: bytes,
    topic: str,
    date: str | None = None,
) -> str | None:
    """Upload a rendered clip into the org's connected Dropbox under
    /B-Roll/<date>/<topic>/<filename>.

    Resolves the Dropbox connection the same way pdf_export.deliver_pdf_to_dropbox
    does (integrations row + refreshed access token). Best-effort: returns the
    Dropbox path on success, None (never raises) when Dropbox isn't connected,
    the server has no OAuth creds, or the upload fails.
    """
    supabase = current_supabase.get()
    if supabase is None or not org_id or not clip_bytes:
        return None

    from packages.integrations.dropbox.client import (
        get_connection,
        get_fresh_access_token,
        upload_file,
    )

    try:
        conn = get_connection(supabase, org_id)
    except Exception as e:  # noqa: BLE001
        print(f"[broll] dropbox connection lookup failed for {org_id}: {e!r}", flush=True)
        return None
    if not conn:
        return None

    client_id = os.environ.get("DROPBOX_CLIENT_ID", "")
    client_secret = os.environ.get("DROPBOX_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("[broll] dropbox OAuth not configured on server; skipping deposit", flush=True)
        return None

    try:
        token = await get_fresh_access_token(supabase, org_id, client_id, client_secret)
    except Exception as e:  # noqa: BLE001
        print(f"[broll] dropbox token resolution failed for {org_id}: {e!r}", flush=True)
        return None

    name = _safe_segment(filename, "clip.mp4")
    if not name.lower().endswith((".mp4", ".mov", ".webm")):
        name += ".mp4"
    dropbox_path = f"{broll_folder_path(topic, date=date)}/{name}"

    try:
        await upload_file(token, dropbox_path, clip_bytes, mode="overwrite")
    except Exception as e:  # noqa: BLE001
        print(f"[broll] dropbox upload failed for {dropbox_path}: {e!r}", flush=True)
        return None

    return dropbox_path


# ── LLM-callable tools ──────────────────────────────────────────────────────
@tool
async def generate_broll_clip(
    prompt: str,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 6,
) -> str:
    """Generate one short b-roll video clip from a prompt via Higgsfield.

    Args:
        prompt: The b-roll scene description to render.
        aspect_ratio: "16:9" (landscape, primary) or "9:16" (portrait, Shorts).
        duration_seconds: Clip length, typically 5-10 seconds.

    Returns a short status string with the clip URL on success, or a clear
    "not configured" message when no Higgsfield key is set (so the run never
    crashes on a missing key).
    """
    from packages.integrations.higgsfield import (
        HiggsfieldUnavailable,
        HiggsfieldError,
        generate_clip,
    )

    try:
        clip = await generate_clip(
            prompt,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            download=False,
        )
    except HiggsfieldUnavailable as e:
        return f"Video generation is not configured yet: {e}"
    except HiggsfieldError as e:
        return f"Clip generation failed: {e}"
    return f"Generated {aspect_ratio} clip ({duration_seconds}s): {clip.url}"


def get_broll_tools():
    """The B-Roll Producer's LLM-callable tools.

    Just the Higgsfield generation tool. Dropbox deposit is a graph-node
    helper (deposit_clip_to_dropbox), not LLM-callable, so the model can't
    file clips on its own.
    """
    return [generate_broll_clip]
