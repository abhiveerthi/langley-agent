from packages.agents.core.base import BaseAgent
from packages.agents.general.agent import GeneralAgent

AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "general": GeneralAgent,
}


def get_agent(slug: str) -> BaseAgent:
    if slug not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {slug}")
    return AGENT_REGISTRY[slug]()


def register_agent(slug: str, agent_class: type[BaseAgent]):
    """Called at startup to register custom agents loaded from DB."""
    AGENT_REGISTRY[slug] = agent_class
