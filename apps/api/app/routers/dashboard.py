from fastapi import APIRouter, Depends
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
