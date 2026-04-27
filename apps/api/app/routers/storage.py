"""
Storage Library endpoints.

Asset metadata lives in `storage_assets` (one row per file in the
`org-assets` bucket). Bytes live in Supabase Storage. The browser uploads
directly to Storage using the user's JWT — RLS on `storage.objects`
restricts paths to `<org_id>/...` — and then POSTs the resulting metadata
here so we can list/filter/tag/search.

Endpoints:
  GET    /api/storage/assets                    list (filters: kind, tag, search, archived)
  POST   /api/storage/assets                    register a just-uploaded asset
  GET    /api/storage/assets/{id}               single asset
  GET    /api/storage/assets/{id}/download-url  short-lived signed URL
  PATCH  /api/storage/assets/{id}               rename / retag / notes
  DELETE /api/storage/assets/{id}               soft-delete (sets archived_at)
  POST   /api/storage/assets/{id}/restore       undo delete

Hard delete (removing the underlying object too) is a separate `purge`
endpoint kept off the list view for v1 — soft-delete is reversible, hard
isn't, and the user should make that decision deliberately.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase

router = APIRouter(tags=["storage"])

BUCKET = "org-assets"

ALLOWED_KINDS = {
    "upload", "brief", "package", "script",
    "thumbnail", "image", "video", "audio", "other",
}


# ── Request bodies ─────────────────────────────────────────────────────────

class RegisterAssetBody(BaseModel):
    """Posted by the client after uploading bytes directly to Supabase Storage."""
    storage_path: str = Field(..., description="Full path inside the org-assets bucket")
    filename: str
    size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    kind: str = "upload"
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    source: Optional[str] = None  # 'user' default; agents will pass their slug
    source_id: Optional[str] = None


class PatchAssetBody(BaseModel):
    filename: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    kind: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────

def _normalize_tags(tags: list[str]) -> list[str]:
    """Strip whitespace, drop empties, dedupe (preserving order)."""
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        v = (t or "").strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _ensure_org_owns_path(org_id: str, storage_path: str) -> None:
    """Cheap path-prefix check so a misbehaving client can't register an
    asset against a foreign org's prefix. Storage RLS would block the upload
    too, but failing fast here keeps tampered metadata out of the list."""
    expected = f"{org_id}/"
    if not storage_path.startswith(expected):
        raise HTTPException(400, f"storage_path must start with '{expected}'")


def _get_or_404(supabase: Client, asset_id: str, org_id: str) -> dict:
    resp = (
        supabase.table("storage_assets")
        .select("*")
        .eq("id", asset_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, "Asset not found")
    return resp.data[0]


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/storage/assets")
async def list_assets(
    kind: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Substring match on filename"),
    archived: bool = Query(False),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    query = (
        supabase.table("storage_assets")
        .select("*")
        .eq("org_id", user.org_id)
    )
    if archived:
        query = query.not_.is_("archived_at", "null")
    else:
        query = query.is_("archived_at", "null")
    if kind:
        if kind not in ALLOWED_KINDS:
            raise HTTPException(400, f"Unknown kind: {kind}")
        query = query.eq("kind", kind)
    if tag:
        # Postgrest array-contains
        query = query.contains("tags", [tag])
    if search:
        query = query.ilike("filename", f"%{search}%")

    resp = query.order("created_at", desc=True).limit(500).execute()
    return resp.data or []


@router.post("/storage/assets")
async def register_asset(
    body: RegisterAssetBody,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    if body.kind not in ALLOWED_KINDS:
        raise HTTPException(400, f"Unknown kind: {body.kind}")
    _ensure_org_owns_path(user.org_id, body.storage_path)

    row = {
        "org_id": user.org_id,
        "storage_path": body.storage_path,
        "filename": body.filename,
        "size_bytes": body.size_bytes,
        "mime_type": body.mime_type,
        "kind": body.kind,
        "tags": _normalize_tags(body.tags),
        "notes": body.notes,
        "source": body.source or "user",
        "source_id": body.source_id,
        "uploaded_by": user.id,
    }
    resp = (
        supabase.table("storage_assets")
        .upsert(row, on_conflict="org_id,storage_path")
        .execute()
    )
    if not resp.data:
        raise HTTPException(500, "Insert returned no row")
    return resp.data[0]


@router.get("/storage/assets/{asset_id}")
async def get_asset(
    asset_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    return _get_or_404(supabase, asset_id, user.org_id)


@router.get("/storage/assets/{asset_id}/download-url")
async def get_download_url(
    asset_id: str,
    expires_in: int = Query(300, ge=10, le=3600, description="Seconds the URL stays valid"),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Return a signed URL the browser can hit directly to download the bytes.

    Signing happens server-side using the service role so callers don't need
    extra storage scopes; the URL expires in `expires_in` seconds (default 5m,
    max 1h)."""
    row = _get_or_404(supabase, asset_id, user.org_id)
    try:
        signed = supabase.storage.from_(BUCKET).create_signed_url(
            row["storage_path"], expires_in
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Could not sign URL: {e}")
    # supabase-py returns a dict like {"signedURL": "...", "signedUrl": "..."}
    # depending on version. Pull the first available key.
    url = (
        signed.get("signedURL")
        or signed.get("signedUrl")
        or signed.get("signed_url")
    )
    if not url:
        raise HTTPException(500, f"Storage didn't return a URL: {signed}")
    return {"url": url, "expires_in": expires_in, "filename": row["filename"]}


@router.patch("/storage/assets/{asset_id}")
async def patch_asset(
    asset_id: str,
    body: PatchAssetBody,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    _get_or_404(supabase, asset_id, user.org_id)  # tenant guard

    patch = body.model_dump(exclude_unset=True)
    if "tags" in patch and patch["tags"] is not None:
        patch["tags"] = _normalize_tags(patch["tags"])
    if "kind" in patch and patch["kind"] is not None:
        if patch["kind"] not in ALLOWED_KINDS:
            raise HTTPException(400, f"Unknown kind: {patch['kind']}")
    if not patch:
        raise HTTPException(400, "No editable fields supplied")
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()

    resp = (
        supabase.table("storage_assets")
        .update(patch)
        .eq("id", asset_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return resp.data[0] if resp.data else {}


@router.delete("/storage/assets/{asset_id}")
async def soft_delete_asset(
    asset_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Soft delete — flips archived_at. The underlying file stays in Storage
    until a future purge endpoint or cron sweep removes it."""
    _get_or_404(supabase, asset_id, user.org_id)
    resp = (
        supabase.table("storage_assets")
        .update({"archived_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", asset_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return resp.data[0] if resp.data else {}


@router.post("/storage/assets/{asset_id}/restore")
async def restore_asset(
    asset_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    _get_or_404(supabase, asset_id, user.org_id)
    resp = (
        supabase.table("storage_assets")
        .update({"archived_at": None})
        .eq("id", asset_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return resp.data[0] if resp.data else {}
