"""
Human-in-the-loop approval endpoints.

Endpoints, all tenancy-scoped via the Bearer-token auth helper:

  GET  /api/approvals                        — list pending approvals
                                               scoped to the caller's org
  POST /api/approvals/{id}/approve           — resume the paused graph;
                                               streams continuation events
                                               as SSE
  POST /api/approvals/{id}/reject            — reject with optional feedback;
                                               agent revises and re-pauses
                                               at approval_gate
  POST /api/approvals/{id}/cancel            — discard the draft entirely;
                                               marks the row 'cancelled' and
                                               does NOT resume the graph

All resolve `(org_id, user_id, supabase)` via `resolve_user` — the same
helper `/chat/stream` uses — and fall back to "dev" when no token is present
so local development without auth still works. The two StreamingResponses
are wrapped in `with_tool_context` so agent tools that read ContextVars on
resume (YouTube client, etc.) see the right tenant.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.auth import resolve_user, with_tool_context
from app.services.approval_store import get_approval_store
from app.services.graph_orchestrator import (
    stream_resume_approved,
    stream_resume_rejected,
)

router = APIRouter(tags=["approvals"])


class RejectBody(BaseModel):
    feedback: Optional[str] = None


@router.get("/approvals")
async def list_approvals(request: Request):
    org_id, _user_id, _supabase = resolve_user(request)
    store = get_approval_store()
    return await store.list_pending(org_id)


@router.post("/approvals/{approval_id}/approve")
async def approve_action(approval_id: str, request: Request):
    """Approve the gated action and stream the continuation.

    The graph resumes at the node after the interrupt (e.g. Brand Manager's
    send_email), runs to completion — or pauses again if there's another gate
    — and streams events the whole way.
    """
    org_id, user_id, supabase = resolve_user(request)
    return StreamingResponse(
        with_tool_context(
            stream_resume_approved(
                approval_id=approval_id,
                reviewer_user_id=user_id,
            ),
            org_id=org_id,
            user_id=user_id,
            supabase=supabase,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/approvals/{approval_id}/reject")
async def reject_action(
    approval_id: str,
    request: Request,
    body: RejectBody | None = None,
):
    """Reject the draft and stream the continuation.

    For Brand Manager, a rejection + feedback runs `revise_pitch` and then
    pauses again at the next approval_gate — a new approvals row is created
    for that gate and emitted on the stream as a `waiting_approval` event.
    """
    feedback = body.feedback if body else None
    org_id, user_id, supabase = resolve_user(request)
    return StreamingResponse(
        with_tool_context(
            stream_resume_rejected(
                approval_id=approval_id,
                reviewer_user_id=user_id,
                feedback=feedback,
            ),
            org_id=org_id,
            user_id=user_id,
            supabase=supabase,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/approvals/{approval_id}/cancel", status_code=204)
async def cancel_action(approval_id: str, request: Request):
    """Discard a pending draft without resuming the graph.

    Different from `reject`: rejection asks the agent to try again (revise
    loop), cancel throws the draft away entirely. The paused LangGraph
    thread state is left as-is — orphaned but harmless — and the row's
    status flips to 'cancelled' so it stops appearing in pending lists.
    """
    org_id, user_id, _supabase = resolve_user(request)
    store = get_approval_store()

    row = await store.get(approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if row.get("org_id") != org_id:
        raise HTTPException(status_code=403, detail="Not your approval")
    if row.get("status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval already resolved (status={row.get('status')})",
        )

    await store.update_status(
        approval_id, status="cancelled", reviewed_by=user_id
    )
    return None
