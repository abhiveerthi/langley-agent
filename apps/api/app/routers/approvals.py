"""
Human-in-the-loop approval endpoints.

Three endpoints:

  GET  /api/approvals                        — list pending approvals (per-org)
  POST /api/approvals/{id}/approve           — resume the paused graph; streams
                                               continuation events as SSE
  POST /api/approvals/{id}/reject            — reject with optional feedback;
                                               Brand Manager revises and
                                               re-pauses at approval_gate

Tenancy is stubbed (`org_id="dev"`, `user_id="dev"`) until backlog item B
(real auth + DB-backed org_profiles) lands. The real implementation will
pull both from `CurrentUser` via `Depends(get_current_user)`.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.services.approval_store import get_approval_store
from app.services.graph_orchestrator import (
    stream_resume_approved,
    stream_resume_rejected,
)

router = APIRouter(tags=["approvals"])


class RejectBody(BaseModel):
    feedback: Optional[str] = None


# ── Dev-mode tenancy stubs ────────────────────────────────────────────────
# Replace these with real auth when backlog item B lands.
_DEV_ORG_ID = "dev"
_DEV_USER_ID = "dev"


@router.get("/approvals")
async def list_approvals():
    store = get_approval_store()
    return await store.list_pending(_DEV_ORG_ID)


@router.post("/approvals/{approval_id}/approve")
async def approve_action(approval_id: str):
    """Approve the gated action and stream the continuation.

    The graph resumes at the node after the interrupt (e.g. Brand Manager's
    send_email), runs to completion — or pauses again if there's another gate
    — and streams events the whole way.
    """
    return StreamingResponse(
        stream_resume_approved(
            approval_id=approval_id,
            reviewer_user_id=_DEV_USER_ID,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/approvals/{approval_id}/reject")
async def reject_action(approval_id: str, body: RejectBody | None = None):
    """Reject the draft and stream the continuation.

    For Brand Manager, a rejection + feedback runs `revise_pitch` and then
    pauses again at the next approval_gate — a new approvals row is created
    for that gate and emitted on the stream as a `waiting_approval` event.
    """
    feedback = body.feedback if body else None
    return StreamingResponse(
        stream_resume_rejected(
            approval_id=approval_id,
            reviewer_user_id=_DEV_USER_ID,
            feedback=feedback,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
