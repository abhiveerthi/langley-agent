from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.message import add_messages
from typing import TypedDict, Annotated, Any
import os

from packages.agents.core.peer_context import load_peer_context
from packages.integrations.context import current_supabase


class BaseAgentState(TypedDict):
    messages: Annotated[list, add_messages]
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
        self._custom_checkpointer = None
        self.graph = self.build_graph()

    async def get_checkpointer(self):
        if self._custom_checkpointer is not None:
            return self._custom_checkpointer
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

    async def _load_peer_context_node(self, state: dict) -> dict:
        """Hydrate `state.metadata.peer_context` with the latest outputs of
        peer agents in the same org.

        Reusable across agents — wire it into your graph (typically right
        after `load_profile`) and the rendered prompts can reference
        `peer_context.latest_brief`, `peer_context.latest_package`, etc.
        Reads `current_supabase` and the state's `org_id`; gracefully
        no-ops in dev mode (returns empty PeerContext) so local runs work
        without Supabase configured. See packages/agents/core/peer_context.py.
        """
        org_id = state.get("org_id") or ""
        supabase = current_supabase.get()
        peer = await load_peer_context(org_id, supabase)
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "peer_context": peer.model_dump(mode="json"),
            }
        }

    def get_approval_request(self, state: dict) -> dict | None:
        """Describe the action that is gated at an interrupt.

        Called by the API runtime when the graph is paused at one of
        `interrupt_before_nodes`. Returns the payload the frontend needs to
        render an approval card — or None if the agent has no HITL gates.

        Shape (matches the `approvals` table in migrations/001_core.sql):
            {
                "action_type":    "send_email" | "update_video_metadata" | ...,
                "action_payload": {...}   # arbitrary action-specific fields
                "preview":        "short human-readable summary for the card",
            }
        """
        return None

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
