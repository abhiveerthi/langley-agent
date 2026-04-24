"""
Human-in-the-loop approval endpoints.

Three endpoints:

  GET  /api/approvals                        — list pending approvals for the
                                               signed-in user's org
  POST /api/approvals/{id}/approve           — resume the paused graph; streams
                                               continuation events as SSE
  POST /api/approvals/{id}/reject            — reject with optional feedback;
                                               the agent's revise branch runs
                                               and re-pauses at approval_gate

Auth + tenancy come from `Depends(get_current_user)`. Both resume entry points
wrap the orchestrator's async generator with the same `_with_tool_context`
helper used by /chat/stream — the resumed graph needs `current_supabase`,
`current_org_id`, and `current_user_id` set so tools like Publisher's
`update_video_metadata` can reach the org's OAuth connection.
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase
from app.services.approval_store import get_approval_store
from app.services.graph_orchestrator import (
    stream_resume_approved,
    stream_resume_rejected,
)
from packages.integrations.context import (
    current_org_id,
    current_supabase,
    current_user_id,
)

router = APIRouter(tags=["approvals"])


class RejectBody(BaseModel):
    feedback: Optional[str] = None


async def _with_tool_context(
    gen: AsyncIterator[str],
    *,
    org_id: str,
    user_id: str,
    supabase: Client,
) -> AsyncIterator[str]:
    current_org_id.set(org_id)
    current_user_id.set(user_id)
    current_supabase.set(supabase)
    async for event in gen:
        yield event


@router.get("/approvals")
async def list_approvals(
    user: CurrentUser = Depends(get_current_user),
):
    store = get_approval_store()
    return await store.list_pending(user.org_id)


@router.post("/approvals/{approval_id}/approve")
async def approve_action(
    approval_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Approve the gated action and stream the continuation.

    The graph resumes at the node after the interrupt (e.g. Publisher's
    `push_metadata`), runs to completion — or pauses again if there's another
    gate — and streams events the whole way.
    """
    return StreamingResponse(
        _with_tool_context(
            stream_resume_approved(
                approval_id=approval_id,
                reviewer_user_id=user.id,
            ),
            org_id=user.org_id,
            user_id=user.id,
            supabase=supabase,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/approvals/{approval_id}/reject")
async def reject_action(
    approval_id: str,
    body: RejectBody | None = None,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Reject the draft and stream the continuation.

    The agent's revise branch runs with the user's feedback and then pauses
    again at the next approval_gate — a new approvals row is created for that
    gate and emitted on the stream as a `waiting_approval` event.
    """
    feedback = body.feedback if body else None
    return StreamingResponse(
        _with_tool_context(
            stream_resume_rejected(
                approval_id=approval_id,
                reviewer_user_id=user.id,
                feedback=feedback,
            ),
            org_id=user.org_id,
            user_id=user.id,
            supabase=supabase,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
