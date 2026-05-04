"""
Identity + active-org metadata for the authenticated user.

  GET /api/me

Returns the current user's display data and the active org's name + slug,
in one shape so the Topbar can render initials, name, and the workspace
label without N round trips. Adding multi-org switcher in v2 will extend
this with an `available_orgs` list; for v1 single-org-per-user, the
single org is implicit.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase

router = APIRouter(tags=["me"])


class UserMe(BaseModel):
    id: str
    email: str
    full_name: str | None = None
    avatar_url: str | None = None
    initials: str  # 1-2 characters derived for the Topbar avatar fallback


class OrgMe(BaseModel):
    id: str
    name: str
    slug: str


class MeResponse(BaseModel):
    user: UserMe
    org: OrgMe
    role: str  # 'owner' | 'limited' | 'member'


def _initials_for(full_name: str | None, email: str) -> str:
    """Two-letter initials from full_name when present, else first two
    letters of the email local-part. Always uppercase."""
    if full_name:
        parts = [p for p in full_name.strip().split() if p]
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        if len(parts) == 1 and parts[0]:
            return parts[0][:2].upper()
    local = (email or "").split("@", 1)[0]
    return (local[:2] or "?").upper()


@router.get("/me", response_model=MeResponse)
async def get_me(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    user_resp = (
        supabase.table("users")
        .select("id, email, full_name, avatar_url")
        .eq("id", user.id)
        .limit(1)
        .execute()
    )
    user_row = user_resp.data[0] if user_resp.data else {
        "id": user.id, "email": user.email, "full_name": None, "avatar_url": None,
    }

    org_resp = (
        supabase.table("orgs")
        .select("id, name, slug")
        .eq("id", user.org_id)
        .limit(1)
        .execute()
    )
    org_row = org_resp.data[0] if org_resp.data else {
        "id": user.org_id, "name": "", "slug": "",
    }

    return MeResponse(
        user=UserMe(
            id=user_row["id"],
            email=user_row.get("email") or user.email,
            full_name=user_row.get("full_name"),
            avatar_url=user_row.get("avatar_url"),
            initials=_initials_for(user_row.get("full_name"), user_row.get("email") or user.email),
        ),
        org=OrgMe(id=org_row["id"], name=org_row.get("name", ""), slug=org_row.get("slug", "")),
        role=user.role,
    )
