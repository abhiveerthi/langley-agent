"""
Agent → Storage export helper.

Every agent's run produces some kind of artifact: Strategist briefs, Publisher
packages, Brand Manager pitches, Community Manager triage reports. The chat
surface shows them once; the DB tables capture the structured form. But the
creator's mental model is "all my files in one place" — that's the Storage
Library at /app/storage. This helper drops a human-readable copy of each
artifact into the same `org-assets` bucket the user uploads to, registered
through the same `storage_assets` table the Storage page reads.

Path layout matches the API's upload endpoint exactly so storage RLS works
out of the box:

    <org_id>/<kind>/<unix_ms>-<safe_filename>

Source attribution lets the UI badge agent-generated assets and lets future
re-syncs (e.g. "regenerate the v2 of brief X") find the original row:

    source     = agent slug (e.g. 'strategist')
    source_id  = the underlying entity id (e.g. strategist_briefs.id)

Best-effort by design. Export failure logs and returns None — never raise,
because the agent's primary output (DB row, chat reply) has already shipped
and a flaky storage write should not break the user-facing flow.
"""
from __future__ import annotations

import re
import time
from typing import Literal

from packages.integrations.context import current_supabase


_BUCKET = "org-assets"

# Mirrors the check constraint on storage_assets.kind. Keep in sync with
# the latest migration (currently 015).
ExportKind = Literal[
    "brief", "package", "script", "pitch", "report",
    "thumbnail", "image", "video", "audio", "other",
]

# Same whitelist the API uses (apps/api/app/routers/storage.py:_FILENAME_SAFE).
# Anything outside [A-Za-z0-9._-] gets `_` so an agent-supplied filename can
# never escape its kind prefix.
_FILENAME_SAFE = re.compile(r"[^a-zA-Z0-9._-]")


def _safe_filename(name: str) -> str:
    name = (name or "file").strip() or "file"
    return _FILENAME_SAFE.sub("_", name)


async def export_to_storage(
    *,
    org_id: str,
    agent_slug: str,
    kind: ExportKind,
    filename: str,
    content: bytes | str,
    mime_type: str,
    source_id: str | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> str | None:
    """Upload `content` into the org-assets bucket and register a
    storage_assets row attributed to `agent_slug`.

    Returns the storage_path on success, None on any failure (no Supabase
    in context, missing org_id, bucket write error, row insert error).
    The caller should not branch on success — this is a side-channel, not
    the agent's primary output.
    """
    supabase = current_supabase.get()
    if supabase is None or not org_id:
        return None

    raw = content.encode("utf-8") if isinstance(content, str) else content
    if not raw:
        return None

    safe_name = _safe_filename(filename)
    ts = int(time.time() * 1000)
    storage_path = f"{org_id}/{kind}/{ts}-{safe_name}"

    try:
        # The supabase storage client is synchronous — a blocking HTTP POST.
        # Offload to a thread: small markdown artifacts barely noticed, but
        # the Content Agent ships multi-MB podcast audio through here from a
        # task that shares the event loop with the whole API.
        import asyncio

        await asyncio.to_thread(
            supabase.storage.from_(_BUCKET).upload,
            storage_path,
            raw,
            {"content-type": mime_type, "cache-control": "3600"},
        )
    except Exception as e:
        print(f"[storage_export] bucket upload failed for {storage_path}: {e!r}", flush=True)
        return None

    row = {
        "org_id": org_id,
        "storage_path": storage_path,
        "filename": filename or safe_name,
        "size_bytes": len(raw),
        "mime_type": mime_type,
        "kind": kind,
        "tags": list(tags or []),
        "notes": notes,
        "source": agent_slug,
        "source_id": source_id,
    }
    try:
        supabase.table("storage_assets").upsert(
            row, on_conflict="org_id,storage_path"
        ).execute()
    except Exception as e:
        print(f"[storage_export] row insert failed for {storage_path}: {e!r}", flush=True)
        # Bytes are already uploaded but unindexed. Acceptable for a
        # best-effort path; a future janitor can reconcile orphans by
        # diffing bucket listing vs storage_assets.
        return None

    return storage_path


async def export_pdf_to_storage(
    *,
    org_id: str,
    agent_slug: str,
    kind: ExportKind,
    filename: str,
    title: str,
    markdown_body: str,
    subtitle: str | None = None,
    brand_name: str | None = None,
    source_id: str | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> str | None:
    """Render `markdown_body` into a polished PDF and archive it in the
    org-assets bucket — the same `kind` as the Markdown/JSON copy, so the
    PDF shows up in the Storage Library next to it.

    Thin wrapper over `render_pdf` + `export_to_storage`, kept here so callers
    don't have to wire the two together. `filename` should carry a `.pdf`
    extension; one is appended if missing. Best-effort: PDF rendering failure
    or a missing context returns None and never raises (matches the contract
    of `export_to_storage`).
    """
    if not (markdown_body or "").strip():
        return None

    safe_name = filename if filename.lower().endswith(".pdf") else f"{filename}.pdf"

    try:
        # Late import: reportlab is only needed on the PDF path, and importing
        # it lazily keeps storage_export importable in environments without it.
        from packages.agents.core.pdf_export import render_pdf

        pdf_bytes = render_pdf(
            title, markdown_body, subtitle=subtitle, brand_name=brand_name
        )
    except Exception as e:
        print(f"[storage_export] pdf render failed for {safe_name}: {e!r}", flush=True)
        return None

    return await export_to_storage(
        org_id=org_id,
        agent_slug=agent_slug,
        kind=kind,
        filename=safe_name,
        content=pdf_bytes,
        mime_type="application/pdf",
        source_id=source_id,
        tags=tags,
        notes=notes,
    )
