from fastapi import APIRouter, Depends
from app.dependencies import get_current_user, CurrentUser, get_supabase
from supabase import Client
from datetime import datetime, timezone

router = APIRouter(tags=["approvals"])


@router.get("/approvals")
async def list_approvals(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("approvals")
        .select("*, agents:requested_by_agent")
        .eq("org_id", user.org_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.post("/approvals/{approval_id}/approve")
async def approve_action(
    approval_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("approvals")
        .update({
            "status": "approved",
            "reviewed_by": user.id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", approval_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]


@router.post("/approvals/{approval_id}/reject")
async def reject_action(
    approval_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("approvals")
        .update({
            "status": "rejected",
            "reviewed_by": user.id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", approval_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]
