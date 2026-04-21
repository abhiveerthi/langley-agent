"""
LangGraph Studio entry point.

Exposes all live agent graphs for local dev/inspection via `langgraph dev`.
The LangGraph platform manages its own checkpointing — do not pass one here.
Production runs use AsyncPostgresSaver configured in BaseAgent.compile().

The legacy scaffolds (general/research/intel/comms) are intentionally NOT
exposed here — they live in-tree as reference patterns but are not part
of the live Marcus product.
"""
from packages.agents.strategist.agent import StrategistAgent
from packages.agents.publisher.agent import PublisherAgent
from packages.agents.community_manager.agent import CommunityManagerAgent
from packages.agents.brand_manager.agent import BrandManagerAgent
from packages.agents.editor.agent import EditorAgent


def _compile(agent_cls):
    """Instantiate an agent and compile its graph with its interrupt_before list.

    The platform handles checkpointing; we just supply the interrupt points so
    Studio's HITL approval flow pauses at the right nodes.
    """
    agent = agent_cls()
    return agent.graph.compile(interrupt_before=agent.interrupt_before_nodes)


strategist = _compile(StrategistAgent)
publisher = _compile(PublisherAgent)
community_manager = _compile(CommunityManagerAgent)
brand_manager = _compile(BrandManagerAgent)
editor = _compile(EditorAgent)
