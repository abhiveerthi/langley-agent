"""
Strategist router — read-only listing of past weekly briefs.

The Strategist agent persists each `WeeklyBrief` it composes into the
`strategist_briefs` table (see migration 004_strategist_briefs.sql); this
endpoint surfaces them on the Strategist dashboard so the user can see
what's been generated without scrolling chat history.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase

router = APIRouter(tags=["strategist"])


@router.get("/strategist/briefs")
async def list_briefs(
    limit: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    resp = (
        supabase.table("strategist_briefs")
        .select("id, headline, ideas, created_at, thread_id")
        .eq("org_id", user.org_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []
