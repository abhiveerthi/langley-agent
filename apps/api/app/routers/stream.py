from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.services.graph_orchestrator import stream_new_run

router = APIRouter(tags=["chat-stream"])


class ChatStreamRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    agent_slug: str = "general"
    # org_id / user_id will come from auth once tenancy lands (backlog: B).
    # For now the orchestrator uses these dev defaults.
    org_id: Optional[str] = None
    user_id: Optional[str] = None


@router.post("/chat/stream")
async def chat_stream(body: ChatStreamRequest, request: Request):
    thread_id = body.thread_id or str(uuid4())
    run_id = str(uuid4())

    # Tenancy is stubbed — backlog item B will replace these with values
    # resolved from the authenticated user's session.
    org_id = body.org_id or "dev"
    user_id = body.user_id or "dev"

    return StreamingResponse(
        stream_new_run(
            agent_slug=body.agent_slug,
            message=body.message,
            thread_id=thread_id,
            org_id=org_id,
            user_id=user_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-Id": thread_id,
            "X-Run-Id": run_id,
        },
    )
