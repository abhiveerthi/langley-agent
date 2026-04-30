"""
Brand Manager router — read + light-write of brand deals.

Deals are auto-written by Brand Manager's `_send_email_node` after an
approved pitch goes out via Resend (see
`packages/agents/brand_manager/deals.py`). This module surfaces the
pipeline on the Brand Manager dashboard and lets the user move a deal
across the stage Kanban (drag-drop fires the PATCH).

The full lifecycle is:
  pitched → replied → negotiating → signed
                                    ↘ declined / paused
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase

router = APIRouter(tags=["brand-manager"])


# Match the CHECK constraint on `brand_deals.stage` (migration 006_brand_deals.sql).
DealStage = Literal["pitched", "replied", "negotiating", "signed", "declined", "paused"]


class UpdateDealRequest(BaseModel):
    """Patch a brand deal — used by the dashboard's Kanban drag-drop and
    eventually a deal-detail edit form. Stage is the hot field; notes is
    the open-ended annotation slot. Other deal fields (recipient, subject)
    are immutable from the UI — they reflect what was actually sent."""
    stage: Optional[DealStage] = None
    notes: Optional[str] = None


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


@router.patch("/brand-manager/deals/{deal_id}")
async def update_deal(
    deal_id: str,
    body: UpdateDealRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Update a deal's stage or notes. Drag-drop on the Kanban fires this
    with `{stage}`; future deal-detail edit fires with `{notes}`. Always
    bumps `last_updated_at` so the column re-orders by recency without
    needing a separate position field."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        # Nothing to update — return the current row so the FE doesn't have
        # to handle a no-op response shape.
        result = (
            supabase.table("brand_deals")
            .select("*")
            .eq("id", deal_id)
            .eq("org_id", user.org_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Deal not found")
        return result.data[0]

    # Bump last_updated_at explicitly. `brand_deals.last_updated_at` has a
    # default of `now()` for inserts but no trigger for updates; without
    # this, manual stage moves wouldn't bubble the deal to the top of its
    # column.
    updates["last_updated_at"] = datetime.now(timezone.utc).isoformat()

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
