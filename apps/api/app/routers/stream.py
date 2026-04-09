import json
from uuid import uuid4
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from packages.agents.registry import get_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

router = APIRouter(tags=["chat-stream"])


class ChatStreamRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    agent_slug: str = "general"


@router.post("/chat/stream")
async def chat_stream(body: ChatStreamRequest):
    thread_id = body.thread_id or str(uuid4())
    run_id = str(uuid4())

    async def event_stream():
        agent = get_agent(body.agent_slug)
        agent._custom_checkpointer = MemorySaver()
        app = await agent.compile()

        input_data = {
            "messages": [HumanMessage(content=body.message)],
            "org_id": "dev",
            "user_id": "dev",
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
                            # content can be a string or a list of content blocks
                            content = msg.content
                            if isinstance(content, list):
                                # Extract text from content blocks, skip tool_use blocks
                                text_parts = [
                                    block.get("text", "") for block in content
                                    if isinstance(block, dict) and block.get("type") == "text"
                                ]
                                content = "".join(text_parts)

                            if content:
                                yield f"data: {json.dumps({'type': 'token', 'data': {'content': content}})}\n\n"

                            # Also emit tool calls if any
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
