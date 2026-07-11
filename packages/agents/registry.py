import json
from pathlib import Path

from packages.agents.core.base import BaseAgent
from packages.agents.strategist.agent import StrategistAgent
from packages.agents.publisher.agent import PublisherAgent
from packages.agents.community_manager.agent import CommunityManagerAgent
from packages.agents.brand_manager.agent import BrandManagerAgent
from packages.agents.editor.agent import EditorAgent
from packages.agents.image_reader.agent import ImageReaderAgent
from packages.agents.broll.agent import BRollAgent
from packages.agents.content.agent import ContentAgent


AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "strategist": StrategistAgent,
    "publisher": PublisherAgent,
    "community-manager": CommunityManagerAgent,
    "brand-manager": BrandManagerAgent,
    "editor": EditorAgent,
    "image-reader": ImageReaderAgent,
    "broll": BRollAgent,
    "content": ContentAgent,
}


# Maps each registered slug to its on-disk directory name. Slugs use
# kebab-case (URL-friendly, mention-friendly); module dirs use snake_case
# because they're Python identifiers. The mismatch is intentional and
# isolated to this map.
_AGENT_DIRS: dict[str, str] = {
    "strategist": "strategist",
    "publisher": "publisher",
    "community-manager": "community_manager",
    "brand-manager": "brand_manager",
    "editor": "editor",
    "image-reader": "image_reader",
    "broll": "broll",
    "content": "content",
}


def get_agent(slug: str) -> BaseAgent:
    if slug not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {slug}")
    return AGENT_REGISTRY[slug]()


def register_agent(slug: str, agent_class: type[BaseAgent]):
    """Called at startup to register custom agents loaded from DB."""
    AGENT_REGISTRY[slug] = agent_class


def default_agent_seeds(org_id: str) -> list[dict]:
    """Return the rows that should be inserted into `agents` for a new org.

    Read from each registered agent's manifest.json so the seed stays in
    sync without a parallel hardcoded list. The signup hook in
    apps/api/app/dependencies.py upserts these on first auth; the matching
    one-time backfill for existing orgs lives in
    supabase/migrations/014_seed_default_agents.sql.

    The editor is seeded with `active=false` because its manifest declares
    `status: coming-soon` — that keeps it out of @mention autocomplete
    (which filters `active=true`) while still letting direct dispatch
    invoke its "not yet wired" stub system prompt.
    """
    rows: list[dict] = []
    base = Path(__file__).resolve().parent
    for slug, dirname in _AGENT_DIRS.items():
        manifest_path = base / dirname / "manifest.json"
        with manifest_path.open("r", encoding="utf-8") as f:
            m = json.load(f)
        rows.append({
            "org_id": org_id,
            "slug": slug,
            "name": m.get("name", slug),
            "description": m.get("description", ""),
            "icon": m.get("icon"),
            "capabilities": m.get("capabilities", []),
            "tools": m.get("tools", []),
            "is_system": True,
            "active": m.get("status") != "coming-soon",
        })
    return rows
