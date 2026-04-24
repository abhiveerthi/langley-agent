"""
Per-tenant profile loader.

Reads YAML files in config/orgs/ and config/niches/ and resolves them into
a typed OrgProfile. Schema is intentionally a 1:1 map to a future
`org_profiles` Postgres table — when DB-backed multi-tenancy ships, only
the loader function changes; everything that consumes OrgProfile stays put.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ── Where the YAML lives ──────────────────────────────────────────────────
# Resolves relative to the repo root regardless of where the process starts.
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[3]  # …/Marcus-V2
CONFIG_DIR = _REPO_ROOT / "config"
ORGS_DIR = CONFIG_DIR / "orgs"
NICHES_DIR = CONFIG_DIR / "niches"

# Default org slug used when no org_id is supplied (e.g. when poking a
# graph in Studio without filling in the Org Id field). Keeps existing
# Langley-flavoured behaviour as the safety-net default.
DEFAULT_ORG_SLUG = "langley-outdoors-academy"


# ── Pydantic models ──────────────────────────────────────────────────────
class Brand(BaseModel):
    name: str
    voice: str
    primary_email: str


class ResearchCategory(BaseModel):
    slug: str
    label: str
    query: str


class Niche(BaseModel):
    slug: str
    display_name: str
    audience_descriptor: str
    audience_size: str | None = None
    default_voice: str | None = None
    research_categories: list[ResearchCategory] = Field(default_factory=list)
    report_sections: list[str] = Field(default_factory=list)
    intel_brief_sections: list[str] = Field(default_factory=list)
    lead_categories: list[str] = Field(default_factory=list)
    trends_query_focus: str = ""
    content_idea_format_hint: str = ""


class YoutubeChannel(BaseModel):
    channel_id: str | None = None


class OrgProfile(BaseModel):
    org_id: str
    brand: Brand
    niche: Niche
    youtube: YoutubeChannel = Field(default_factory=YoutubeChannel)
    owners: list[str] = Field(default_factory=list)


# ── Loaders ──────────────────────────────────────────────────────────────
def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_niche_preset(slug: str) -> dict[str, Any]:
    return _read_yaml(NICHES_DIR / f"{slug}.yaml")


def _merge_niche(preset: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge: any key present in `overrides` replaces the preset value.

    We deliberately do NOT deep-merge lists (categories, sections) — if the
    org wants to customize them, they replace the whole list. Keeps semantics
    simple and predictable.
    """
    merged = dict(preset)
    for key, value in (overrides or {}).items():
        if value is None:
            continue
        merged[key] = value
    return merged


def load_profile(org_slug: str | None) -> OrgProfile:
    """Load a fully-resolved OrgProfile by org slug.

    - If `org_slug` is empty/None, falls back to DEFAULT_ORG_SLUG.
    - Reads config/orgs/<slug>.yaml. If the file doesn't exist (e.g. the
      caller passed a UUID from an auto-provisioned personal workspace that
      has no YAML yet), falls back to DEFAULT_ORG_SLUG instead of raising.
    - If the org file's `niche` block has a `preset:` key, loads
      config/niches/<preset>.yaml and merges (org overrides preset).
    - Validates and returns an OrgProfile pydantic model.
    """
    slug = (org_slug or DEFAULT_ORG_SLUG).strip()
    org_path = ORGS_DIR / f"{slug}.yaml"
    if not org_path.exists():
        org_path = ORGS_DIR / f"{DEFAULT_ORG_SLUG}.yaml"
    org_data = _read_yaml(org_path)

    niche_block = org_data.get("niche") or {}
    preset_slug = niche_block.pop("preset", None)
    if preset_slug:
        preset = _load_niche_preset(preset_slug)
        niche_block = _merge_niche(preset, niche_block)
    org_data["niche"] = niche_block

    return OrgProfile.model_validate(org_data)
