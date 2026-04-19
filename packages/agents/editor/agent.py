from langgraph.graph import StateGraph, END, START
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.editor.prompts import EDITOR_SYSTEM_PROMPT


class EditorAgent(BaseAgent):
    slug = "editor"
    name = "Editor"
    description = "Cuts long-form videos into ready-to-post shorts. (Coming soon — video worker not yet available.)"
    model = "claude-haiku-4-5-20251001"

    def __init__(self):
        self.llm = ChatAnthropic(model=self.model)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(BaseAgentState)
        graph.add_node("agent", self._agent_node)
        graph.add_edge(START, "agent")
        graph.add_edge("agent", END)
        return graph

    async def _agent_node(self, state: BaseAgentState):
        messages = [SystemMessage(content=EDITOR_SYSTEM_PROMPT)] + state["messages"]
        response = await self.llm.ainvoke(messages)
        return {"messages": [response]}
