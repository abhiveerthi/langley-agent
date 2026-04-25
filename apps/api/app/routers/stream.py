from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import resolve_user, with_tool_context
from app.services.graph_orchestrator import stream_new_run

router = APIRouter(tags=["chat-stream"])


class ChatStreamRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    agent_slug: str = "general"
    # Dev overrides — only used when no Authorization header is present.
    org_id: Optional[str] = None
    user_id: Optional[str] = None


@router.post("/chat/stream")
async def chat_stream(body: ChatStreamRequest, request: Request):
    thread_id = body.thread_id or str(uuid4())
    run_id = str(uuid4())

    resolved_org, resolved_user, supabase = resolve_user(request)
    org_id = body.org_id or resolved_org
    user_id = body.user_id or resolved_user

    return StreamingResponse(
        with_tool_context(
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
