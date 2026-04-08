from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from typing import TypedDict, Any
import os


class BaseAgentState(TypedDict):
    messages: list[dict]
    org_id: str
    user_id: str
    thread_id: str
    task_id: str | None
    metadata: dict[str, Any]


class BaseAgent:
    slug: str = ""
    name: str = ""
    description: str = ""
    tools: list = []
    model: str = "claude-haiku-4-5-20251001"

    def __init__(self):
        self.graph = self.build_graph()

    async def get_checkpointer(self):
        return AsyncPostgresSaver.from_conn_string(os.environ["DATABASE_URL"])

    async def compile(self):
        checkpointer = await self.get_checkpointer()
        return self.graph.compile(
            checkpointer=checkpointer,
            interrupt_before=self.interrupt_before_nodes,
        )

    @property
    def interrupt_before_nodes(self) -> list[str]:
        """Override to specify nodes that require human approval."""
        return []

    def build_graph(self) -> StateGraph:
        """Override to define the agent's graph."""
        raise NotImplementedError

    async def run(self, input_data: dict, thread_id: str, stream: bool = False):
        app = await self.compile()
        config = {"configurable": {"thread_id": thread_id}}
        if stream:
            return app.astream_events(input_data, config=config, version="v2")
        return await app.ainvoke(input_data, config=config)

    async def resume(self, thread_id: str, approved: bool, payload: dict | None = None):
        """Resume a paused graph after human approval."""
        app = await self.compile()
        config = {"configurable": {"thread_id": thread_id}}
        if not approved:
            await app.aupdate_state(
                config,
                {"approval_result": "rejected", "approval_payload": payload},
            )
        return await app.ainvoke(None, config=config)

    async def get_state(self, thread_id: str):
        app = await self.compile()
        config = {"configurable": {"thread_id": thread_id}}
        return await app.aget_state(config)
