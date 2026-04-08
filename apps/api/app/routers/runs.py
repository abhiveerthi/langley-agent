from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_user, CurrentUser, get_supabase
from supabase import Client
from typing import Optional

router = APIRouter(tags=["runs"])


@router.get("/runs")
async def list_runs(
    status: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    query = (
        supabase.table("agent_runs")
        .select("*, agents(name, slug, icon)")
        .eq("org_id", user.org_id)
    )
    if status:
        query = query.eq("status", status)
    if agent_id:
        query = query.eq("agent_id", agent_id)
    result = query.order("started_at", desc=True).limit(100).execute()
    return result.data


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("agent_runs")
        .select("*, agents(name, slug, icon)")
        .eq("id", run_id)
        .eq("org_id", user.org_id)
        .single()
        .execute()
    )
    return result.data


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("agent_runs")
        .update({"status": "cancelled"})
        .eq("id", run_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]
