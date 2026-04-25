"""
Cross-agent shared context — "the moat".

What the Strategist learns, the Publisher uses; what the Publisher ships, the
Community Manager fields questions on; what the Community Manager hears, the
Brand Manager cites when pitching sponsors. This module is how that flow is
wired: every agent that opts in adds a `load_peer_context` node at graph start
that hydrates `state.metadata.peer_context` with the latest outputs of its
peers, scoped to the current org.

Two pieces:

  - `PeerContext` — Pydantic model with one field per peer artifact. Every
    field is Optional so agents can render conditionally. New peers (Publisher,
    Community Manager, future) add a field here without breaking existing
    agents.

  - `load_peer_context(org_id, supabase) -> PeerContext` — pulls the latest
    brief / package / etc. from typed Postgres tables. Gracefully degrades:
    missing Supabase, "dev" org_id, or a missing table all return an empty
    PeerContext rather than raising. Agents always get *something* back.
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


# ── Per-artifact summary models ───────────────────────────────────────────
# These are the shapes downstream agents read. Keep them small — they go into
# every system prompt that opts into peer context. Bigger/more detail belongs
# behind an explicit fetch tool, not here.

class StrategistBriefSummary(BaseModel):
    """Latest weekly brief — read by Publisher (for title direction),
    Brand Manager (for pitch framing), and CM (for reply tone)."""
    headline: str
    ideas: list[dict] = Field(default_factory=list)
    created_at: str | None = None


class PublisherPackageSummary(BaseModel):
    """Latest published / pending package — read by CM (for replies that
    reference what just shipped) and Brand Manager (for media-kit numbers)."""
    video_id: str
    video_title: str
    status: str
    description: str | None = None
    youtube_pushed_at: str | None = None
    created_at: str | None = None


class DealSummary(BaseModel):
    """One row from the Brand Manager's deal pipeline. Read by Strategist
    (briefs can cite "we're negotiating with X" when relevant) and by
    Brand Manager itself for "don't pitch a brand we're already in
    conversation with" deduplication."""
    brand_name: str
    stage: str
    recipient: str | None = None
    last_updated_at: str | None = None


class PeerContext(BaseModel):
    """Per-org snapshot of peer-agent outputs at the start of a run."""
    latest_brief: StrategistBriefSummary | None = None
    latest_package: PublisherPackageSummary | None = None
    # Up to N most-recently-touched deals across all stages. Agents that
    # care about pipeline state (Brand Manager, Strategist) render these
    # in their prompts.
    active_deals: list[DealSummary] = Field(default_factory=list)

    def has_any(self) -> bool:
        return (
            self.latest_brief is not None
            or self.latest_package is not None
            or bool(self.active_deals)
        )


# ── Loader ────────────────────────────────────────────────────────────────

def _is_real_uuid(value: str | None) -> bool:
    """True if `value` parses as a UUID. Dev-mode `org_id="dev"` returns False
    so we skip Supabase reads (which would fail on a non-UUID column)."""
    if not value:
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


async def load_peer_context(org_id: str | None, supabase: Any) -> PeerContext:
    """Hydrate a PeerContext for the given org from the typed peer tables.

    Returns an empty PeerContext (all fields None) when:
      - `supabase` is None (Supabase not configured — local dev path)
      - `org_id` is not a real UUID (e.g. dev fallback "dev")
      - any underlying table is missing or the query errors

    No exceptions propagate — peer context is a nicety, not a hard dependency.
    """
    if supabase is None or not _is_real_uuid(org_id):
        return PeerContext()

    return PeerContext(
        latest_brief=_fetch_latest_brief(org_id, supabase),
        latest_package=_fetch_latest_package(org_id, supabase),
        active_deals=_fetch_active_deals(org_id, supabase),
    )


def _fetch_latest_brief(org_id: str, supabase: Any) -> StrategistBriefSummary | None:
    try:
        result = (
            supabase.table("strategist_briefs")
            .select("headline, ideas, created_at")
            .eq("org_id", org_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        return None

    if not result.data:
        return None
    row = result.data[0]
    return StrategistBriefSummary(
        headline=row.get("headline", ""),
        ideas=row.get("ideas") or [],
        created_at=row.get("created_at"),
    )


def _fetch_active_deals(org_id: str, supabase: Any, limit: int = 5) -> list[DealSummary]:
    """Read the most-recently-touched rows from `brand_deals`. Returns []
    when the table doesn't exist (pre-migration), the org has no deals yet,
    or any DB error — peer agents should never fail because pipeline data
    is unavailable. Limit is small on purpose: we ship ~5 rows into every
    agent prompt that opts into peer_context, so we keep them brief."""
    try:
        result = (
            supabase.table("brand_deals")
            .select("brand_name, stage, recipient, last_updated_at")
            .eq("org_id", org_id)
            .order("last_updated_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception:
        return []

    if not result.data:
        return []
    return [
        DealSummary(
            brand_name=row.get("brand_name", ""),
            stage=row.get("stage", ""),
            recipient=row.get("recipient"),
            last_updated_at=row.get("last_updated_at"),
        )
        for row in result.data
    ]


def _fetch_latest_package(org_id: str, supabase: Any) -> PublisherPackageSummary | None:
    """Read the Publisher's latest package — the table lives on
    `feat/publisher` until that branch merges. We query optimistically and
    swallow the inevitable 'relation publisher_packages does not exist'
    error so this loader never blocks an agent run."""
    try:
        result = (
            supabase.table("publisher_packages")
            .select("video_id, video_title, status, description, "
                    "youtube_pushed_at, created_at, updated_at")
            .eq("org_id", org_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        return None

    if not result.data:
        return None
    row = result.data[0]
    return PublisherPackageSummary(
        video_id=row.get("video_id", ""),
        video_title=row.get("video_title", ""),
        status=row.get("status", ""),
        description=row.get("description"),
        youtube_pushed_at=row.get("youtube_pushed_at"),
        created_at=row.get("created_at"),
    )
