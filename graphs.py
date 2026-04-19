"""
LangGraph Studio entry point.

Exposes all agent graphs for local dev/inspection via `langgraph dev`.
The LangGraph platform manages its own checkpointing — do not pass one here.
Production runs use AsyncPostgresSaver configured in BaseAgent.compile().
"""
from packages.agents.general.agent import GeneralAgent
from packages.agents.research.agent import ResearchAgent
from packages.agents.intel.agent import IntelAgent
from packages.agents.comms.agent import CommsAgent


def _compile(agent_cls):
    """Instantiate an agent and compile its graph (no checkpointer — platform handles it)."""
    agent = agent_cls()
    return agent.graph.compile()


general_agent = _compile(GeneralAgent)
research_agent = _compile(ResearchAgent)
intel_agent = _compile(IntelAgent)
comms_agent = _compile(CommsAgent)
