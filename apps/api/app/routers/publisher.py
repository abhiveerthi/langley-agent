"""
Publisher router — REST endpoints for the Publisher agent's packages.

Endpoints:

  GET    /api/publisher/packages                     list packages for current org
  GET    /api/publisher/packages/{id}                single package
  POST   /api/publisher/packages                     create + kick off generation
  POST   /api/publisher/packages/{id}/regenerate     regenerate one field of a package
  POST   /api/publisher/packages/{id}/push           kick off push flow (gated on approval)
  GET    /api/publisher/packages/{id}/approval       pending youtube_metadata_update approval

The agent is invoked via the shared graph orchestrator. Runs kick off in a
background task that carries the request's tenancy ContextVars (org_id,
user_id, supabase client) into the worker — without those, tools like
update_video_metadata can't reach the OAuth connection.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase
from app.services.graph_orchestrator import stream_new_run
from packages.integrations.context import (
    current_org_id,
    current_supabase,
    current_user_id,
)

router = APIRouter(tags=["publisher"])


# ── Request bodies ─────────────────────────────────────────────────────────

class CreatePackageRequest(BaseModel):
    video_id: str
    video_title: Optional[str] = None


REGEN_FIELDS = {
    "title_variants",
    "description",
    "tags",
    "chapters",
    "thumbnail_ideas",
    "social.twitter",
    "social.newsletter",
}


class RegenerateRequest(BaseModel):
    field: str
    feedback: Optional[str] = None


class PushRequest(BaseModel):
    selected_title: Optional[str] = None


class SendNewsletterRequest(BaseModel):
    """Optional override for the newsletter recipient. When omitted the
    Publisher graph defaults to the org's brand.primary_email (self-send
    preview). Pass an explicit address to send to a single subscriber or
    a small list — Gmail's per-day quota (500 consumer / 2000 Workspace)
    means this isn't a substitute for a real newsletter platform."""
    to: Optional[str] = None


class PatchRequest(BaseModel):
    """Any subset of editable fields. Anything omitted is left unchanged."""
    title_variants: Optional[list[str]] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    chapters: Optional[list[dict]] = None
    thumbnail_ideas: Optional[list[str]] = None
    social: Optional[dict] = None


# ── Helpers ────────────────────────────────────────────────────────────────

async def _run_in_background(
    gen: AsyncIterator[str],
    *,
    org_id: str,
    user_id: str,
    supabase: Client,
    package_id: str | None = None,
) -> None:
    """Drain the orchestrator's SSE generator to completion / pause.

    ContextVars are set here (not at the router boundary) because the request
    handler's context is torn down as soon as the JSON response is returned;
    the background task needs its own snapshot.

    If the run blows up before the persist_package node, we flip the package
    row so the UI stops spinning on "generating" forever and the user can see
    what happened instead.
    """
    import logging
    import traceback
    log = logging.getLogger("publisher.background")

    current_org_id.set(org_id)
    current_user_id.set(user_id)
    current_supabase.set(supabase)
    try:
        async for _ in gen:
            pass
    except Exception as e:
        log.exception("Publisher background run failed (package_id=%s)", package_id)
        if package_id:
            try:
                (
                    supabase.table("publisher_packages")
                    .update({
                        "status": "draft",
                        "warning": f"Generation failed: {e}"[:500],
                    })
                    .eq("id", package_id)
                    .execute()
                )
            except Exception:
                log.exception("Failed to mark package as errored")
        # Print to stderr too so uvicorn's console shows it during dev.
        traceback.print_exc()


def _get_package_or_404(supabase: Client, org_id: str, package_id: str) -> dict:
    resp = (
        supabase.table("publisher_packages")
        .select("*")
        .eq("id", package_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, "Package not found")
    return resp.data[0]


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/publisher/packages")
async def list_packages(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    resp = (
        supabase.table("publisher_packages")
        .select("*")
        .eq("org_id", user.org_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return resp.data or []


@router.get("/publisher/packages/{package_id}")
async def get_package(
    package_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    return _get_package_or_404(supabase, user.org_id, package_id)


@router.post("/publisher/packages")
async def create_package(
    body: CreatePackageRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Insert a generating-status row, then spawn the agent to fill it in.

    Upsert on (org_id, video_id) so re-packaging the same video returns the
    same row instead of duplicating. If a row already exists in a terminal
    status (draft/pushed), it's reset to generating so the agent re-runs.
    """
    existing = (
        supabase.table("publisher_packages")
        .select("id, status")
        .eq("org_id", user.org_id)
        .eq("video_id", body.video_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        package_id = existing.data[0]["id"]
        supabase.table("publisher_packages").update({
            "status": "generating",
            "video_title": body.video_title or existing.data[0].get("video_title") or body.video_id,
        }).eq("id", package_id).execute()
    else:
        created = (
            supabase.table("publisher_packages")
            .insert({
                "org_id": user.org_id,
                "video_id": body.video_id,
                "video_title": body.video_title or body.video_id,
                "status": "generating",
            })
            .execute()
        )
        package_id = created.data[0]["id"]

    thread_id = str(uuid4())
    gen = stream_new_run(
        agent_slug="publisher",
        message=f"Package video {body.video_id}",
        thread_id=thread_id,
        org_id=user.org_id,
        user_id=user.id,
        extra_state={
            "intent": "create_package",
            "video_id": body.video_id,
            "video_title": body.video_title or body.video_id,
            "package_id": package_id,
        },
    )
    asyncio.create_task(_run_in_background(
        gen, org_id=user.org_id, user_id=user.id, supabase=supabase, package_id=package_id,
    ))
    return {"package_id": package_id, "thread_id": thread_id}


@router.post("/publisher/packages/{package_id}/regenerate")
async def regenerate_field(
    package_id: str,
    body: RegenerateRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    if body.field not in REGEN_FIELDS:
        raise HTTPException(400, f"Unsupported field: {body.field}")

    pkg = _get_package_or_404(supabase, user.org_id, package_id)

    thread_id = str(uuid4())
    gen = stream_new_run(
        agent_slug="publisher",
        message=f"Regenerate {body.field} for package {package_id}",
        thread_id=thread_id,
        org_id=user.org_id,
        user_id=user.id,
        extra_state={
            "intent": "regenerate_field",
            "package_id": package_id,
            "video_id": pkg.get("video_id"),
            "video_title": pkg.get("video_title"),
            "regen_field": body.field,
            "regen_feedback": body.feedback,
        },
    )
    asyncio.create_task(_run_in_background(
        gen, org_id=user.org_id, user_id=user.id, supabase=supabase, package_id=package_id,
    ))
    return {"thread_id": thread_id}


@router.post("/publisher/packages/{package_id}/regenerate-all")
async def regenerate_all(
    package_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Re-run the full create_package flow on an existing row.

    Keeps the row id + video_id + video_title, resets status to `generating`,
    and spawns the agent. Existing content stays visible in the UI until the
    agent's persist_package node overwrites it.
    """
    pkg = _get_package_or_404(supabase, user.org_id, package_id)
    supabase.table("publisher_packages").update({
        "status": "generating",
        "warning": None,
    }).eq("id", package_id).execute()

    thread_id = str(uuid4())
    gen = stream_new_run(
        agent_slug="publisher",
        message=f"Package video {pkg['video_id']}",
        thread_id=thread_id,
        org_id=user.org_id,
        user_id=user.id,
        extra_state={
            "intent": "create_package",
            "video_id": pkg["video_id"],
            "video_title": pkg.get("video_title") or pkg["video_id"],
            "package_id": package_id,
        },
    )
    asyncio.create_task(_run_in_background(
        gen, org_id=user.org_id, user_id=user.id, supabase=supabase, package_id=package_id,
    ))
    return {"package_id": package_id, "thread_id": thread_id}


@router.delete("/publisher/packages/{package_id}")
async def delete_package(
    package_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Delete a package row. Any linked approval row has approval_id set to
    null via the FK's on-delete action, but the approvals row itself stays
    (audit trail)."""
    _get_package_or_404(supabase, user.org_id, package_id)  # tenant guard
    supabase.table("publisher_packages").delete().eq("id", package_id).execute()
    return {"status": "deleted", "package_id": package_id}


@router.post("/publisher/packages/{package_id}/push")
async def push_package(
    package_id: str,
    body: PushRequest | None = None,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    pkg = _get_package_or_404(supabase, user.org_id, package_id)
    if pkg.get("status") == "generating":
        raise HTTPException(409, "Package is still generating — try again when status=draft")

    thread_id = str(uuid4())
    gen = stream_new_run(
        agent_slug="publisher",
        message=f"Push package {package_id} to YouTube",
        thread_id=thread_id,
        org_id=user.org_id,
        user_id=user.id,
        extra_state={
            "intent": "push_metadata",
            "package_id": package_id,
            "video_id": pkg.get("video_id"),
            "video_title": pkg.get("video_title"),
            "selected_title": (body.selected_title if body else None),
        },
    )
    asyncio.create_task(_run_in_background(
        gen, org_id=user.org_id, user_id=user.id, supabase=supabase, package_id=package_id,
    ))
    return {"thread_id": thread_id}


@router.post("/publisher/packages/{package_id}/post-x")
async def post_to_x(
    package_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Kick off the X push flow for a package's social.twitter copy.

    Pauses at the approval gate; the client polls /approval to surface the dialog.
    """
    pkg = _get_package_or_404(supabase, user.org_id, package_id)
    if pkg.get("status") == "generating":
        raise HTTPException(409, "Package is still generating — try again when status=draft")
    tweet = ((pkg.get("social") or {}).get("twitter") or "").strip()
    if not tweet:
        raise HTTPException(400, "Package has no tweet copy yet — regenerate social.twitter first")

    thread_id = str(uuid4())
    gen = stream_new_run(
        agent_slug="publisher",
        message=f"Post tweet for package {package_id}",
        thread_id=thread_id,
        org_id=user.org_id,
        user_id=user.id,
        extra_state={
            "intent": "push_x",
            "package_id": package_id,
            "video_id": pkg.get("video_id"),
            "video_title": pkg.get("video_title"),
            "proposed_tweet": tweet,
        },
    )
    asyncio.create_task(_run_in_background(
        gen, org_id=user.org_id, user_id=user.id, supabase=supabase, package_id=package_id,
    ))
    return {"thread_id": thread_id}


@router.post("/publisher/packages/{package_id}/send-newsletter")
async def send_newsletter(
    package_id: str,
    body: SendNewsletterRequest | None = None,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Kick off the newsletter send flow for a package.

    Pulls subject + body from the package's social.newsletter_{subject,body}
    fields (falling back to the legacy `social.newsletter` blob) and pauses
    at the approval gate. The recipient defaults to the org's
    brand.primary_email unless `body.to` is supplied.
    """
    pkg = _get_package_or_404(supabase, user.org_id, package_id)
    if pkg.get("status") == "generating":
        raise HTTPException(409, "Package is still generating — try again when status=draft")

    social = pkg.get("social") or {}
    has_body = bool(
        (social.get("newsletter_body") or "").strip()
        or (social.get("newsletter") or "").strip()
    )
    if not has_body:
        raise HTTPException(
            400,
            "Package has no newsletter copy yet — regenerate social.newsletter_body first",
        )

    thread_id = str(uuid4())
    extra_state: dict = {
        "intent": "push_newsletter",
        "package_id": package_id,
        "video_id": pkg.get("video_id"),
        "video_title": pkg.get("video_title"),
    }
    if body and body.to:
        extra_state["newsletter_recipient"] = body.to

    gen = stream_new_run(
        agent_slug="publisher",
        message=f"Send newsletter for package {package_id}",
        thread_id=thread_id,
        org_id=user.org_id,
        user_id=user.id,
        extra_state=extra_state,
    )
    asyncio.create_task(_run_in_background(
        gen, org_id=user.org_id, user_id=user.id, supabase=supabase, package_id=package_id,
    ))
    return {"thread_id": thread_id}


@router.patch("/publisher/packages/{package_id}")
async def patch_package(
    package_id: str,
    body: PatchRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Manually edit any subset of package fields.

    Only fields present in the request body are updated; everything else is
    left untouched. Used by the detail page's per-section inline editor.
    """
    _get_package_or_404(supabase, user.org_id, package_id)  # tenant guard

    patch: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        patch[key] = value

    if len(patch) == 1:
        # Only updated_at — nothing meaningful to change.
        raise HTTPException(400, "No editable fields supplied")

    resp = (
        supabase.table("publisher_packages")
        .update(patch)
        .eq("id", package_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(404, "Package not found")
    return resp.data[0]


@router.get("/publisher/packages/{package_id}/approval")
async def get_pending_approval(
    package_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Find the most-recent pending approval for this package, if any.

    Returns either a `youtube_metadata_update` or `x_post` row — the UI keys
    off `action_type` to render the right dialog body.
    """
    _get_package_or_404(supabase, user.org_id, package_id)  # tenant guard
    resp = (
        supabase.table("approvals")
        .select("*")
        .eq("org_id", user.org_id)
        .in_("action_type", ["youtube_metadata_update", "x_post"])
        .eq("status", "pending")
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    for row in resp.data or []:
        payload = row.get("action_payload") or {}
        if payload.get("package_id") == package_id:
            return row
    return None
