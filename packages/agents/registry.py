from packages.agents.core.base import BaseAgent
from packages.agents.general.agent import GeneralAgent
from packages.agents.research.agent import ResearchAgent
from packages.agents.intel.agent import IntelAgent
from packages.agents.comms.agent import CommsAgent
from packages.agents.strategist.agent import StrategistAgent
from packages.agents.publisher.agent import PublisherAgent
from packages.agents.community_manager.agent import CommunityManagerAgent
from packages.agents.brand_manager.agent import BrandManagerAgent
from packages.agents.editor.agent import EditorAgent

AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    # Backroom team
    "strategist": StrategistAgent,
    "publisher": PublisherAgent,
    "community-manager": CommunityManagerAgent,
    "brand-manager": BrandManagerAgent,
    "editor": EditorAgent,
    # Legacy scaffolds (kept for now)
    "general": GeneralAgent,
    "research": ResearchAgent,
    "intel": IntelAgent,
    "comms": CommsAgent,
}


def get_agent(slug: str) -> BaseAgent:
    if slug not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {slug}")
    return AGENT_REGISTRY[slug]()


def register_agent(slug: str, agent_class: type[BaseAgent]):
    """Called at startup to register custom agents loaded from DB."""
    AGENT_REGISTRY[slug] = agent_class
