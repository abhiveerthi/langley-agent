"""
Jinja2 prompt renderer.

Templates live alongside each agent at packages/agents/<agent>/templates/<name>.j2.
Every render call automatically injects:

    profile  — full OrgProfile pydantic model
    brand    — profile.brand
    niche    — profile.niche
    today    — datetime.now() ISO date string

Plus any **extra kwargs the caller passes.

Persona name "Marcus" is NOT a template variable — it stays hardcoded inside
the templates as the AgentOS product brand.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from packages.agents.core.profile import OrgProfile

_AGENTS_ROOT = Path(__file__).resolve().parent.parent  # …/packages/agents


@lru_cache(maxsize=None)
def _env_for(agent_slug: str) -> Environment:
    """Build (and cache) a Jinja env scoped to one agent's templates folder."""
    template_dir = _AGENTS_ROOT / agent_slug / "templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
        # StrictUndefined: a missing variable raises immediately instead of
        # silently rendering an empty string. Catches profile/template drift.
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(
    agent_slug: str,
    template_name: str,
    profile: OrgProfile,
    **extra,
) -> str:
    """Render a template by name.

    Example:
        render("research", "interpret.j2", profile=profile)
    """
    env = _env_for(agent_slug)
    template = env.get_template(template_name)
    context = {
        "profile": profile,
        "brand": profile.brand,
        "niche": profile.niche,
        "today": datetime.now().strftime("%B %d, %Y"),
        **extra,
    }
    return template.render(**context)
