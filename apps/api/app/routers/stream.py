from uuid import uuid4
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from supabase import create_client

from app.config import get_settings
from app.services.graph_orchestrator import stream_new_run
from packages.integrations.context import (
    current_org_id,
    current_supabase,
    current_user_id,
)

router = APIRouter(tags=["chat-stream"])


class ChatStreamRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    agent_slug: str = "general"
    # Dev overrides — only used when no Authorization header is present.
    org_id: Optional[str] = None
    user_id: Optional[str] = None


def _resolve_user(request: Request) -> tuple[str, str, object]:
    """Resolve (org_id, user_id, supabase_client) from the Authorization header.

    Falls back to "dev" defaults when Supabase is unconfigured or the token is
    missing/invalid so local development without auth still works.
    """
    settings = get_settings()
    supabase = (
        create_client(settings.supabase_url, settings.supabase_service_key)
        if settings.supabase_url and settings.supabase_service_key
        else None
    )
    if supabase is None:
        return "dev", "dev", None

    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return "dev", "dev", supabase

    token = auth.split(" ", 1)[1]
    try:
        user_resp = supabase.auth.get_user(token)
        user = getattr(user_resp, "user", None)
        if not user:
            return "dev", "dev", supabase
        membership = (
            supabase.table("org_members")
            .select("org_id")
            .eq("user_id", user.id)
            .limit(1)
            .execute()
        )
        if not membership.data:
            return "dev", user.id, supabase
        return membership.data[0]["org_id"], user.id, supabase
    except Exception:
        return "dev", "dev", supabase


async def _with_tool_context(
    gen: AsyncIterator[str],
    *,
    org_id: str,
    user_id: str,
    supabase,
) -> AsyncIterator[str]:
    """Set the ContextVars that agent tools read (org_id / user_id / supabase)
    for the lifetime of the stream, then delegate to the orchestrator."""
    current_org_id.set(org_id)
    current_user_id.set(user_id)
    current_supabase.set(supabase)
    async for event in gen:
        yield event


@router.post("/chat/stream")
async def chat_stream(body: ChatStreamRequest, request: Request):
    thread_id = body.thread_id or str(uuid4())
    run_id = str(uuid4())

    resolved_org, resolved_user, supabase = _resolve_user(request)
    org_id = body.org_id or resolved_org
    user_id = body.user_id or resolved_user

    return StreamingResponse(
        _with_tool_context(
            stream_new_run(
                agent_slug=body.agent_slug,
                message=body.message,
                thread_id=thread_id,
                org_id=org_id,
                user_id=user_id,
            ),
            org_id=org_id,
            user_id=user_id,
            supabase=supabase,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-Id": thread_id,
            "X-Run-Id": run_id,
        },
    )
