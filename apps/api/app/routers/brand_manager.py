"""
Brand Manager router — read + update endpoints for the deal pipeline.

Deals are auto-written by Brand Manager's `_send_email_node` after an
approved pitch goes out via Resend (see `packages/agents/brand_manager/deals.py`).
This router surfaces the pipeline on the Brand Manager dashboard and
lets the user move deals through stages by hand from the detail panel.

Endpoints:
  GET    /api/brand-manager/dashboard         — combined deals + pitches
                                                count for the dashboard
                                                (one round trip)
  GET    /api/brand-manager/deals             — list, latest-first
  GET    /api/brand-manager/deals/{id}        — single deal + linked tasks
  PATCH  /api/brand-manager/deals/{id}        — update stage / notes

The dashboard endpoint exists because the `/app/agents/brand-manager`
page used to fire `GET /deals` + `GET /approvals` in parallel, each of
which redoes the Bearer-token verify + `org_members` lookup before its
own query. Three round trips became one once we noticed the dashboard
page was the slowest in the app to load.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase

router = APIRouter(tags=["brand-manager"])


# Stage values mirror the brand_deals CHECK constraint (006_brand_deals.sql).
# Defined as a Literal so a bad value comes back as a 422 instead of a
# DB-side check_violation that surfaces as a 500.
DealStage = Literal["pitched", "replied", "negotiating", "signed", "declined", "paused"]


class UpdateDealRequest(BaseModel):
    """Stage moves come from the dashboard's stage selector. `notes` is a
    free-text field the user can attach in the detail panel — useful for
    "left voicemail Tuesday" / "asked for media kit" annotations between
    stage changes. Both fields are optional; the detail panel sends
    whichever one the user touched."""
    stage: Optional[DealStage] = None
    notes: Optional[str] = None


@router.get("/brand-manager/dashboard")
async def get_dashboard(
    deal_limit: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Single round trip for the dashboard's first paint.

    Returns:
      deals          — same list as `GET /deals`, latest-first
      pending_pitches — count of pending approvals with
                        action_type='send_email' (the BM-relevant ones)

    The page used to fire 3 parallel calls (deals + approvals + youtube
    status); each repeated the Bearer-token verify and `org_members`
    lookup before its own query. Folding deals + approvals here cuts the
    auth/membership work from 3× to 1× and saves two round trips. The
    YouTube pill stays separate because it hits the YouTube API, which
    we don't want gating dashboard paint.
    """
    deals_resp = (
        supabase.table("brand_deals")
        .select("*")
        .eq("org_id", user.org_id)
        .order("last_updated_at", desc=True)
        .limit(deal_limit)
        .execute()
    )

    # Server-side filter on action_type — the FE used to fetch every pending
    # approval and filter to send_email client-side, which scales badly when
    # other agents start producing approvals. Selecting just `id` keeps the
    # response small (we only need the count).
    pitches_resp = (
        supabase.table("approvals")
        .select("id")
        .eq("org_id", user.org_id)
        .eq("status", "pending")
        .eq("action_type", "send_email")
        .execute()
    )

    return {
        "deals": deals_resp.data or [],
        "pending_pitches": len(pitches_resp.data or []),
    }


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


@router.get("/brand-manager/deals/{deal_id}")
async def get_deal(
    deal_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Single deal + the tasks linked to it. The detail panel renders the
    deal header and a small linked-tasks list below — one round trip
    keeps the UX snappy when the panel opens.

    Tasks include the agent rollup (`agents(name, slug, icon)`) so the
    panel can badge auto-generated follow-ups ('from Brand Manager')
    without a second join.
    """
    deal_resp = (
        supabase.table("brand_deals")
        .select("*")
        .eq("id", deal_id)
        .eq("org_id", user.org_id)
        .limit(1)
        .execute()
    )
    if not deal_resp.data:
        raise HTTPException(status_code=404, detail="Deal not found")

    tasks_resp = (
        supabase.table("tasks")
        .select("*, agents(name, slug, icon)")
        .eq("org_id", user.org_id)
        .eq("deal_id", deal_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return {"deal": deal_resp.data[0], "tasks": tasks_resp.data or []}


@router.patch("/brand-manager/deals/{deal_id}")
async def update_deal(
    deal_id: str,
    body: UpdateDealRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Move a deal through stages by hand or attach a note. The trigger on
    `brand_deals` updates `last_updated_at` automatically, so an empty PATCH
    is rejected (defensive — would be a no-op anyway, but a 400 surfaces
    the bug to the FE rather than silently re-rendering).

    Stage validation lives in the Pydantic Literal — invalid values come
    back as 422 before they hit the DB CHECK constraint.
    """
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="At least one of stage or notes must be provided")

    result = (
        supabase.table("brand_deals")
        .update(updates)
        .eq("id", deal_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")
    return result.data[0]
