import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.config import get_settings
from packages.agents.registry import get_agent
from packages.integrations.context import (
    current_org_id,
    current_supabase,
    current_user_id,
)
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from supabase import create_client

router = APIRouter(tags=["chat-stream"])


class ChatStreamRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    agent_slug: str = "general"


def _resolve_user(request: Request) -> tuple[str, str, object]:
    """Return (org_id, user_id, supabase_client). Falls back to dev defaults."""
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_service_key) if settings.supabase_url else None
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


@router.post("/chat/stream")
async def chat_stream(body: ChatStreamRequest, request: Request):
    thread_id = body.thread_id or str(uuid4())
    run_id = str(uuid4())

    org_id, user_id, supabase = _resolve_user(request)

    async def event_stream():
        current_org_id.set(org_id)
        current_user_id.set(user_id)
        current_supabase.set(supabase)

        agent = get_agent(body.agent_slug)
        agent._custom_checkpointer = MemorySaver()
        app = await agent.compile()

        input_data = {
            "messages": [HumanMessage(content=body.message)],
            "org_id": org_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "task_id": None,
            "metadata": {},
        }
        config = {"configurable": {"thread_id": thread_id}}

        try:
            async for chunk in app.astream(input_data, config=config, stream_mode="updates"):
                for node, data in chunk.items():
                    messages = data.get("messages", [])
                    for msg in messages:
                        if isinstance(msg, AIMessage) and msg.content:
                            content = msg.content
                            if isinstance(content, list):
                                text_parts = [
                                    block.get("text", "") for block in content
                                    if isinstance(block, dict) and block.get("type") == "text"
                                ]
                                content = "".join(text_parts)

                            if content:
                                yield f"data: {json.dumps({'type': 'token', 'data': {'content': content}})}\n\n"

                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    yield f"data: {json.dumps({'type': 'tool_call_start', 'data': {'id': tc.get('id', ''), 'tool': tc.get('name', ''), 'input': tc.get('args', {}), 'status': 'running'}})}\n\n"

                        elif isinstance(msg, ToolMessage):
                            yield f"data: {json.dumps({'type': 'tool_call_end', 'data': {'id': msg.tool_call_id, 'tool': msg.name, 'output': str(msg.content)[:500], 'status': 'success'}})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'data': {}})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"

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
