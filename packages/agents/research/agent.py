from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.research.prompts import RESEARCH_SYSTEM_PROMPT
from packages.agents.research.tools import get_research_tools


class ResearchAgent(BaseAgent):
    slug = "research"
    name = "Research Agent"
    description = "Political intelligence gathering, analysis, and content strategy for Langley Firearms Academy."
    model = "claude-sonnet-4-6"

    def __init__(self):
        self.tools = get_research_tools()
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
        messages = [SystemMessage(content=RESEARCH_SYSTEM_PROMPT)] + state["messages"]
        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}

    def _should_use_tools(self, state: BaseAgentState):
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "end"
