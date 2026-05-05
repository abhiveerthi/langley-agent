from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_user, CurrentUser, get_supabase
from supabase import Client
from datetime import datetime, timedelta, timezone

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/kpis")
async def get_kpis(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    runs = (
        supabase.table("agent_runs")
        .select("id, status, cost_usd, started_at, completed_at, agent_id")
        .eq("org_id", user.org_id)
        .gte("started_at", since)
        .execute()
    )

    tasks = (
        supabase.table("tasks")
        .select("id, status")
        .eq("org_id", user.org_id)
        .gte("created_at", since)
        .execute()
    )

    total_runs = len(runs.data)
    completed_runs = sum(1 for r in runs.data if r["status"] == "completed")
    success_rate = (completed_runs / total_runs * 100) if total_runs > 0 else 0
    total_cost = sum(float(r["cost_usd"] or 0) for r in runs.data)
    tasks_completed = sum(1 for t in tasks.data if t["status"] == "completed")

    return {
        "total_runs": total_runs,
        "success_rate": round(success_rate, 1),
        "tasks_completed": tasks_completed,
        "total_cost": round(total_cost, 2),
    }


@router.get("/dashboard/overview")
async def get_overview(
    runs_limit: int = Query(8, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Combined feed for `/app/agents` (the entry-point landing page).

    Returns recent runs + pending approvals in a single round trip.
    Replaces the prior pattern of two parallel `GET /runs` + `GET /approvals`
    calls, each redoing the Bearer-token verify + `org_members` lookup
    before its own query — same speedup story as PR #38 for BM.

    The runs query uses `?limit=<runs_limit>` server-side instead of the
    FE pulling every run and slicing client-side. That matters as the
    runs table grows: an org with thousands of runs would otherwise
    fetch and discard them all on every page mount.
    """
    runs_resp = (
        supabase.table("agent_runs")
        .select("*, agents(name, slug, icon)")
        .eq("org_id", user.org_id)
        .order("started_at", desc=True)
        .limit(runs_limit)
        .execute()
    )

    approvals_resp = (
        supabase.table("approvals")
        .select("*")
        .eq("org_id", user.org_id)
        .eq("status", "pending")
        .order("created_at", desc=True)
        .execute()
    )

    return {
        "runs": runs_resp.data or [],
        "pending_approvals": approvals_resp.data or [],
    }
