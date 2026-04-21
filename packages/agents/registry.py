from packages.agents.core.base import BaseAgent
from packages.agents.strategist.agent import StrategistAgent
from packages.agents.publisher.agent import PublisherAgent
from packages.agents.community_manager.agent import CommunityManagerAgent
from packages.agents.brand_manager.agent import BrandManagerAgent
from packages.agents.editor.agent import EditorAgent

# The four legacy scaffolds (general/research/intel/comms) live in-tree as
# reference for patterns (e.g. comms/agent.py is the canonical example of
# the classify_intent -> approval_gate -> send_email flow that Brand
# Manager now uses) but are deliberately not registered. The Marcus team
# below is the live roster.

AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    # Marcus team
    "strategist": StrategistAgent,
    "publisher": PublisherAgent,
    "community-manager": CommunityManagerAgent,
    "brand-manager": BrandManagerAgent,
    "editor": EditorAgent,
}


def get_agent(slug: str) -> BaseAgent:
    if slug not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {slug}")
    return AGENT_REGISTRY[slug]()


def register_agent(slug: str, agent_class: type[BaseAgent]):
    """Called at startup to register custom agents loaded from DB."""
    AGENT_REGISTRY[slug] = agent_class
