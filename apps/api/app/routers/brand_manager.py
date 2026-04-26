"""
Brand Manager router — read-only listing of brand deals.

Deals are auto-written by Brand Manager's `_send_email_node` after an
approved pitch goes out via Resend (see `packages/agents/brand_manager/deals.py`).
This endpoint surfaces the pipeline on the Brand Manager dashboard.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase

router = APIRouter(tags=["brand-manager"])


@router.get("/brand-manager/deals")
async def list_deals(
    limit: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    resp = (
        supabase.table("brand_deals")
        .select("*")
        .eq("org_id", user.org_id)
        .order("last_updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []
