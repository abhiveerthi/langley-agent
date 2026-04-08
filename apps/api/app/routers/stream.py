import json
from uuid import uuid4
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from app.dependencies import get_current_user, CurrentUser, get_supabase
from supabase import Client
from packages.agents.registry import get_agent
from packages.agents.core.tracker import RunTracker

router = APIRouter(tags=["chat-stream"])


class ChatStreamRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    agent_slug: str = "general"


@router.post("/chat/stream")
async def chat_stream(
    body: ChatStreamRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    thread_id = body.thread_id or str(uuid4())
    run_id = str(uuid4())

    # Ensure thread exists
    if not body.thread_id:
        supabase.table("threads").insert({
            "id": thread_id,
            "org_id": user.org_id,
            "user_id": user.id,
            "title": body.message[:100],
            "status": "active",
        }).execute()

    # Get agent record for the org
    agent_record = (
        supabase.table("agents")
        .select("id")
        .eq("org_id", user.org_id)
        .eq("slug", body.agent_slug)
        .limit(1)
        .execute()
    )
    agent_id = agent_record.data[0]["id"] if agent_record.data else None

    # Persist user message
    supabase.table("messages").insert({
        "thread_id": thread_id,
        "role": "user",
        "content": body.message,
    }).execute()

    # Create run record
    supabase.table("agent_runs").insert({
        "id": run_id,
        "org_id": user.org_id,
        "thread_id": thread_id,
        "agent_id": agent_id,
        "status": "running",
        "input": {"message": body.message},
    }).execute()

    async def event_stream():
        agent = get_agent(body.agent_slug)
        tracker = RunTracker(run_id, user.org_id, supabase)

        # Build input for the agent
        from langchain_core.messages import HumanMessage
        input_data = {
            "messages": [HumanMessage(content=body.message)],
            "org_id": user.org_id,
            "user_id": user.id,
            "thread_id": thread_id,
            "task_id": None,
            "metadata": {},
        }

        full_response = ""
        async for event in tracker.track(agent, input_data, thread_id):
            if event["type"] == "token":
                full_response += event["data"].get("content", "")
            yield f"data: {json.dumps(event)}\n\n"

        # Persist assistant message
        if full_response:
            supabase.table("messages").insert({
                "thread_id": thread_id,
                "role": "assistant",
                "content": full_response,
                "metadata": {
                    "run_id": run_id,
                    "agent_slug": body.agent_slug,
                },
            }).execute()

        # Update thread title if it was the first message
        if not body.thread_id:
            supabase.table("threads").update({
                "title": body.message[:100],
                "agent_id": agent_id,
            }).eq("id", thread_id).execute()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-Id": thread_id,
            "X-Run-Id": run_id,
        },
    )
