from fastapi import APIRouter, Depends
from app.dependencies import get_current_user, CurrentUser, get_supabase
from supabase import Client

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("notifications")
        .select("*")
        .eq("user_id", user.id)
        .eq("org_id", user.org_id)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )
    return result.data


@router.patch("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("notifications")
        .update({"read": True})
        .eq("id", notification_id)
        .eq("user_id", user.id)
        .execute()
    )
    return result.data[0]


@router.patch("/notifications/read-all")
async def mark_all_read(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    supabase.table("notifications").update({"read": True}).eq(
        "user_id", user.id
    ).eq("read", False).execute()
    return {"ok": True}
