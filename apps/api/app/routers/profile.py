"""
Brand profile endpoints.

  GET    /api/profile     read the current org's brand profile
  PATCH  /api/profile     update any subset of editable fields

Mirrors the `Brand` and `OrgProfile` Pydantic models in
`packages/agents/core/profile.py` — anything new there gets reflected here so
the settings page can edit it. Niche is read-only for now (it references a
YAML preset list); future work can add a niche picker.

The row in `org_profiles` is upserted on PATCH so a freshly-signed-up org
that doesn't have a row yet (no signup hook fired) won't 404 on first save.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase

router = APIRouter(tags=["profile"])


class BrandPatch(BaseModel):
    """All-Optional patch body. Anything omitted is left unchanged.

    Mirrors the column layout in 005_org_profiles + 007_brand_profile_extended."""
    brand_name: str | None = None
    brand_voice: str | None = None
    brand_primary_email: str | None = None
    brand_logo_url: str | None = None
    brand_tagline: str | None = None
    brand_about: str | None = None
    brand_writing_sample: str | None = None
    brand_tone_keywords: list[str] | None = None
    brand_avoid_list: list[str] | None = None
    brand_default_cta: str | None = None
    brand_audience_descriptor: str | None = None


def _profile_response(row: dict | None) -> dict:
    """Shape the response so the frontend can read brand.* directly without
    string-munging column prefixes."""
    if row is None:
        return {
            "brand": {
                "name": None, "voice": None, "primary_email": None,
                "logo_url": None, "tagline": None, "about": None,
                "writing_sample": None, "tone_keywords": [], "avoid_list": [],
                "default_cta": None, "audience_descriptor": None,
            },
            "niche_slug": None,
            "audience_size": None,
            "youtube_channel_id": None,
        }
    return {
        "brand": {
            "name": row.get("brand_name"),
            "voice": row.get("brand_voice"),
            "primary_email": row.get("brand_primary_email"),
            "logo_url": row.get("brand_logo_url"),
            "tagline": row.get("brand_tagline"),
            "about": row.get("brand_about"),
            "writing_sample": row.get("brand_writing_sample"),
            "tone_keywords": list(row.get("brand_tone_keywords") or []),
            "avoid_list": list(row.get("brand_avoid_list") or []),
            "default_cta": row.get("brand_default_cta"),
            "audience_descriptor": row.get("brand_audience_descriptor"),
        },
        "niche_slug": row.get("niche_slug"),
        "audience_size": row.get("audience_size"),
        "youtube_channel_id": row.get("youtube_channel_id"),
    }


@router.get("/profile")
async def get_profile(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    resp = (
        supabase.table("org_profiles")
        .select("*")
        .eq("org_id", user.org_id)
        .limit(1)
        .execute()
    )
    row = resp.data[0] if resp.data else None
    return _profile_response(row)


@router.patch("/profile")
async def patch_profile(
    body: BrandPatch,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    patch: dict[str, Any] = body.model_dump(exclude_unset=True)
    if not patch:
        # Nothing to write — return current state so the client can refresh.
        return await get_profile(user=user, supabase=supabase)

    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    patch["org_id"] = user.org_id

    resp = (
        supabase.table("org_profiles")
        .upsert(patch, on_conflict="org_id")
        .execute()
    )
    row = resp.data[0] if resp.data else None
    return _profile_response(row)
