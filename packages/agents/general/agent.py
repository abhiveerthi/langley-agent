from langgraph.graph import StateGraph, END, START
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.prompts import GENERAL_SYSTEM_PROMPT
from packages.agents.general.tools import get_general_tools


class GeneralAgent(BaseAgent):
    slug = "general"
    name = "General Assistant"
    description = "A helpful AI assistant for general tasks, planning, writing, and analysis."
    model = "claude-haiku-4-5-20251001"

    def __init__(self):
        self.tools = get_general_tools()
        self.llm = ChatAnthropic(model=self.model).bind_tools(self.tools)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(BaseAgentState)

        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._tool_node)

        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent",
            self._should_use_tools,
            {"tools": "tools", "end": END},
        )
        graph.add_edge("tools", "agent")

        return graph

    async def _agent_node(self, state: BaseAgentState):
        messages = [SystemMessage(content=GENERAL_SYSTEM_PROMPT)] + state["messages"]
        response = await self.llm.ainvoke(messages)
        return {"messages": state["messages"] + [response]}

    def _should_use_tools(self, state: BaseAgentState):
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "end"

    async def _tool_node(self, state: BaseAgentState):
        from langgraph.prebuilt import ToolNode
        tool_node = ToolNode(self.tools)
        result = await tool_node.ainvoke(state)
        return result
