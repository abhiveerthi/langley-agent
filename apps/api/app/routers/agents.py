from fastapi import APIRouter, Depends
from app.dependencies import get_current_user, CurrentUser, get_supabase
from supabase import Client

router = APIRouter(tags=["agents"])


@router.get("/agents")
async def list_agents(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("agents")
        .select("*")
        .eq("org_id", user.org_id)
        .eq("active", True)
        .execute()
    )
    return result.data


@router.patch("/agents/{slug}/config")
async def update_agent_config(
    slug: str,
    config: dict,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("agents")
        .update({"config": config})
        .eq("slug", slug)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]


@router.patch("/agents/{slug}/toggle")
async def toggle_agent(
    slug: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    current = (
        supabase.table("agents")
        .select("active")
        .eq("slug", slug)
        .eq("org_id", user.org_id)
        .single()
        .execute()
    )
    new_active = not current.data["active"]
    result = (
        supabase.table("agents")
        .update({"active": new_active})
        .eq("slug", slug)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]
