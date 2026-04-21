from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.agents.community_manager.tools import get_community_manager_tools


class CommunityManagerAgent(BaseAgent):
    slug = "community-manager"
    name = "Community Manager"
    description = "Triages comments, drafts replies in the creator's voice, flags VIPs."
    model = "claude-haiku-4-5-20251001"

    def __init__(self):
        self.tools = get_community_manager_tools()
        self.llm = ChatAnthropic(model=self.model).bind_tools(self.tools)
        self.tool_node = ToolNode(self.tools)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(BaseAgentState)
        graph.add_node("load_profile", self._load_profile_node)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self.tool_node)

        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "agent")
        graph.add_conditional_edges(
            "agent",
            self._should_use_tools,
            {"tools": "tools", "end": END},
        )
        graph.add_edge("tools", "agent")
        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: BaseAgentState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    async def _load_profile_node(self, state: BaseAgentState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    async def _agent_node(self, state: BaseAgentState):
        profile = self._profile(state)
        system_prompt = render("community_manager", "system.j2", profile=profile)
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}

    def _should_use_tools(self, state: BaseAgentState):
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return "end"
