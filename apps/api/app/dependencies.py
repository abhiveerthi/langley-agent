from fastapi import Depends, HTTPException, Request
from supabase import create_client, Client
from app.config import get_settings, Settings
from dataclasses import dataclass


@dataclass
class CurrentUser:
    id: str
    org_id: str
    email: str
    role: str = "member"


def get_supabase(settings: Settings = Depends(get_settings)) -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_key)


async def get_current_user(request: Request, supabase: Client = Depends(get_supabase)) -> CurrentUser:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = auth_header.split(" ")[1]

    try:
        user_response = supabase.auth.get_user(token)
        user = user_response.user
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    membership = (
        supabase.table("org_members")
        .select("org_id, role")
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )

    if membership.data:
        member = membership.data[0]
        return CurrentUser(
            id=user.id,
            org_id=member["org_id"],
            email=user.email,
            role=member["role"],
        )

    # First sign-in: provision a personal workspace.
    member = _provision_personal_workspace(supabase, user)
    return CurrentUser(
        id=user.id,
        org_id=member["org_id"],
        email=user.email,
        role=member["role"],
    )


def _provision_personal_workspace(supabase: Client, user) -> dict:
    # Ensure users row
    meta = getattr(user, "user_metadata", {}) or {}
    full_name = meta.get("full_name") or meta.get("name") or (user.email.split("@")[0] if user.email else None)
    (
        supabase.table("users")
        .upsert(
            {"id": user.id, "email": user.email, "full_name": full_name},
            on_conflict="id",
        )
        .execute()
    )

    # Create or recover a personal org
    org_name = f"{full_name}'s workspace" if full_name else "My workspace"
    slug = f"u-{user.id.replace('-', '')[:10]}"

    try:
        org_row = (
            supabase.table("orgs")
            .insert({"name": org_name, "slug": slug})
            .execute()
            .data[0]
        )
    except Exception:
        # Slug collision — recover existing row
        org_row = (
            supabase.table("orgs")
            .select("id")
            .eq("slug", slug)
            .limit(1)
            .execute()
            .data[0]
        )

    # Idempotent membership (unique on org_id+user_id)
    (
        supabase.table("org_members")
        .upsert(
            {"org_id": org_row["id"], "user_id": user.id, "role": "owner"},
            on_conflict="org_id,user_id",
        )
        .execute()
    )

    return {"org_id": org_row["id"], "role": "owner"}
