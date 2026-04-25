"""
Per-tenant profile loader.

Resolves an `org_id` (UUID for real signed-in tenants, slug for dev fixtures,
or None for unauthed dev) into a typed `OrgProfile` that agents consume.

Two storage backends, one Pydantic schema:
  - **DB (`org_profiles` table)** — the production source. Rows are created
    at signup time by partner's OAuth flow and updated via the settings UI.
    Read first when the loader has Supabase access AND the caller passes a
    real UUID.
  - **YAML (`config/orgs/<slug>.yaml`)** — the dev fixture format. Useful for
    Studio runs and local agent debugging without spinning up Supabase.
    Niche presets stay YAML-only for now (small, stable list).

Loader contract:
  load_profile("123e4567-…")        — DB-only. Raises ProfileNotFound on miss.
  load_profile("langley-outdoors-…") — YAML-only. Raises ProfileNotFound on miss.
  load_profile(None) / load_profile("dev")
                                    — Returns a clearly-fake DEMO profile.
                                      Agents that need real config should
                                      surface a "you're not signed in" error
                                      rather than operate as a real tenant.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from packages.integrations.context import current_supabase


# ── Where the YAML lives ──────────────────────────────────────────────────
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[3]  # …/Marcus-V2
CONFIG_DIR = _REPO_ROOT / "config"
ORGS_DIR = CONFIG_DIR / "orgs"
NICHES_DIR = CONFIG_DIR / "niches"


class ProfileNotFound(Exception):
    """Raised when neither DB nor YAML has a profile for the given identifier.

    Caught at the agent runtime layer to surface "this org isn't set up yet"
    instead of silently serving a fake or default profile."""


# ── Pydantic models ──────────────────────────────────────────────────────
class Brand(BaseModel):
    """Brand identity. Every field is Optional because a freshly-signed-up
    org has only the bits OAuth told us (e.g. channel title → brand name)
    and the rest gets filled in via the settings UI."""
    name: str | None = None
    voice: str | None = None
    primary_email: str | None = None


class Niche(BaseModel):
    """Niche preset. The schema is intentionally lean — `display_name` and
    `audience_descriptor` are referenced by every agent prompt; `lead_categories`
    is referenced by Brand Manager's research/draft prompts. Anything else
    that used to live here belonged to legacy scaffolds and has been removed."""
    slug: str
    display_name: str
    audience_descriptor: str
    audience_size: str | None = None
    lead_categories: list[str] = Field(default_factory=list)


class YoutubeChannel(BaseModel):
    channel_id: str | None = None


def _generic_niche() -> "Niche":
    """Fallback niche used when a profile has no `niche_slug` set yet
    (typical for orgs mid-onboarding). Keeps templates that read
    `{{ niche.display_name }}` from crashing on a bare signup row.

    Agents that genuinely depend on niche-specific behaviour (Brand Manager's
    sponsor categories, Strategist's trend search) will see `slug == "generic"`
    and can surface "pick a niche in settings" rather than producing
    nonsense — that's a future agent-level guard, not the loader's job."""
    return Niche(
        slug="generic",
        display_name="General creator content",
        audience_descriptor="general audience",
        lead_categories=[],
    )


class OrgProfile(BaseModel):
    org_id: str
    brand: Brand = Field(default_factory=Brand)
    # Always non-None so templates can render — see _generic_niche() above.
    niche: Niche = Field(default_factory=_generic_niche)
    youtube: YoutubeChannel = Field(default_factory=YoutubeChannel)
    owners: list[str] = Field(default_factory=list)
    is_fixture: bool = False


# ── Identifier classification ────────────────────────────────────────────
def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _is_dev_fallback(value: str | None) -> bool:
    """The orchestrator passes "dev" / "" / None when there's no real auth."""
    return not value or value.strip().lower() == "dev"


# ── Demo profile (used in unauthed dev mode) ──────────────────────────────
def _demo_profile() -> OrgProfile:
    """A clearly-fake profile returned when there's no real tenant context.

    Marked `is_fixture=True` and the brand name is "Demo Channel" so any
    surfaced output makes the unauthed state obvious to whoever's looking.
    Agents that genuinely need real tenant data should check for this and
    refuse to make external calls (e.g. send emails, post comments)."""
    return OrgProfile(
        org_id="dev",
        brand=Brand(
            name="Demo Channel",
            voice="neutral, professional",
            primary_email="demo@example.com",
        ),
        niche=Niche(
            slug="demo",
            display_name="Demo Niche",
            audience_descriptor="demo audience",
            lead_categories=[],
        ),
        youtube=YoutubeChannel(channel_id=None),
        owners=[],
        is_fixture=True,
    )


# ── YAML helpers ──────────────────────────────────────────────────────────
def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_niche_preset(slug: str) -> dict[str, Any]:
    return _read_yaml(NICHES_DIR / f"{slug}.yaml")


def _resolve_niche(slug_or_block: dict[str, Any] | str | None) -> Niche:
    """Niche on disk is referenced by `preset:` slug with optional inline
    overrides; in DB it's referenced by a single `niche_slug` text column.
    This helper normalizes both into a fully-resolved Niche object —
    falling back to the generic niche when the source is empty or refers
    to an unknown preset."""
    if slug_or_block is None:
        return _generic_niche()

    if isinstance(slug_or_block, str):
        # Bare slug from the DB — load the preset and return it.
        try:
            preset = _load_niche_preset(slug_or_block)
        except FileNotFoundError:
            return _generic_niche()
        return Niche.model_validate(preset)

    # Dict from YAML org file — may have a `preset:` plus overrides.
    block = dict(slug_or_block)
    preset_slug = block.pop("preset", None)
    if preset_slug:
        try:
            preset = _load_niche_preset(preset_slug)
        except FileNotFoundError:
            preset = {}
        merged = {**preset, **{k: v for k, v in block.items() if v is not None}}
        return Niche.model_validate(merged)

    if not block:
        return _generic_niche()
    return Niche.model_validate(block)


# ── DB loader ─────────────────────────────────────────────────────────────
def _load_from_db(org_id: str) -> OrgProfile | None:
    """Read org_profiles row for the given UUID. Returns None on miss or any
    DB failure (the caller decides whether that's fatal)."""
    supabase = current_supabase.get()
    if supabase is None:
        return None
    try:
        result = (
            supabase.table("org_profiles")
            .select("*")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    if not result.data:
        return None

    row = result.data[0]
    return OrgProfile(
        org_id=row["org_id"],
        brand=Brand(
            name=row.get("brand_name"),
            voice=row.get("brand_voice"),
            primary_email=row.get("brand_primary_email"),
        ),
        niche=_resolve_niche(row.get("niche_slug")),
        youtube=YoutubeChannel(channel_id=row.get("youtube_channel_id")),
        owners=list(row.get("owners") or []),
        is_fixture=bool(row.get("is_fixture", False)),
    )


# ── YAML loader ───────────────────────────────────────────────────────────
def _load_from_yaml(slug: str) -> OrgProfile | None:
    """Read config/orgs/<slug>.yaml. Returns None on miss."""
    org_path = ORGS_DIR / f"{slug}.yaml"
    if not org_path.exists():
        return None

    org_data = _read_yaml(org_path)
    return OrgProfile(
        org_id=org_data.get("org_id", slug),
        brand=Brand.model_validate(org_data.get("brand") or {}),
        niche=_resolve_niche(org_data.get("niche")),
        youtube=YoutubeChannel.model_validate(org_data.get("youtube") or {}),
        owners=list(org_data.get("owners") or []),
        is_fixture=bool(org_data.get("is_fixture", False)),
    )


# ── Public entry point ────────────────────────────────────────────────────
def load_profile(org_id_or_slug: str | None) -> OrgProfile:
    """Load a profile by UUID (DB) or slug (YAML).

    Raises ProfileNotFound when no matching record exists in either backend.
    Returns a clearly-fake demo profile when called without auth (org_id is
    None / "" / "dev")."""
    if _is_dev_fallback(org_id_or_slug):
        return _demo_profile()

    identifier = (org_id_or_slug or "").strip()

    if _is_uuid(identifier):
        profile = _load_from_db(identifier)
        if profile is None:
            raise ProfileNotFound(
                f"No org_profiles row for UUID {identifier!r}. "
                "Has signup completed and the row been inserted?"
            )
        return profile

    profile = _load_from_yaml(identifier)
    if profile is None:
        raise ProfileNotFound(
            f"No config/orgs/{identifier}.yaml found. "
            f"Real tenants should pass a UUID; dev fixtures need a YAML file."
        )
    return profile
