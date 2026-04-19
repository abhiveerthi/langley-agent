from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.publisher.prompts import PUBLISHER_SYSTEM_PROMPT
from packages.agents.publisher.tools import get_publisher_tools


class PublisherAgent(BaseAgent):
    slug = "publisher"
    name = "Publisher"
    description = "Ships every video, everywhere. Writes YouTube metadata and repurposes uploads into tweets, LinkedIn posts, and more."
    model = "claude-sonnet-4-6"

    def __init__(self):
        self.tools = get_publisher_tools()
        self.llm = ChatAnthropic(model=self.model).bind_tools(self.tools)
        self.tool_node = ToolNode(self.tools)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(BaseAgentState)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self.tool_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent",
            self._should_use_tools,
            {"tools": "tools", "end": END},
        )
        graph.add_edge("tools", "agent")
        return graph

    async def _agent_node(self, state: BaseAgentState):
        messages = [SystemMessage(content=PUBLISHER_SYSTEM_PROMPT)] + state["messages"]
        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}

    def _should_use_tools(self, state: BaseAgentState):
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return "end"
