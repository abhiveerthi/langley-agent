"""
Content Agent tools + pipeline-ledger helpers.

`get_content_tools()` returns the LLM-callable tools — here a single
`get_pipeline_status` tool the chat lane uses to answer "where's today's
content?" from the `content_pipelines` table.

The pipeline-ledger helpers (`upsert_pipeline_row`, `record_stage`,
`set_pipeline_status`) are NOT LLM tools — they're what the graph's pipeline
nodes call to keep the durable `content_pipelines` row in sync as the run
moves through its stages. All of them follow the repo's best-effort posture:
no Supabase (dev mode) or a non-UUID org means a silent no-op — ledger
bookkeeping must never crash a run.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import tool

from packages.agents.core.peer_context import _is_real_uuid
from packages.integrations.context import current_org_id, current_supabase


# ── Pipeline lifecycle vocabulary ───────────────────────────────────────────
# Kept small on purpose; stages get their own per-stage statuses inside the
# `stages` jsonb instead of inflating this list.
PIPELINE_STATUSES = (
    "detected",          # row created, run not yet through any stage
    "processing",        # stages executing
    "ready_for_review",  # assets generated, queued for the approval chain
    "approved",          # both approval steps cleared
    "publishing",        # publish fan-out in flight
    "published",         # all approved assets live
    "failed",            # a stage errored, or no assets were produced
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client_or_none(org_id: str):
    """Service/request Supabase client, or None when ledger writes should no-op
    (dev mode without Supabase, or a non-UUID dev org id)."""
    supabase = current_supabase.get()
    if supabase is None or not _is_real_uuid(org_id or ""):
        return None
    return supabase


# ── Ledger helpers (graph-node callable, not LLM tools) ─────────────────────

def upsert_pipeline_row(
    org_id: str,
    video_id: str,
    *,
    video_title: str | None = None,
    thread_id: str | None = None,
    status: str = "processing",
) -> dict | None:
    """Create-or-refresh the pipeline row for (org, video). Idempotent via the
    unique(org_id, video_id) constraint, so a scheduler retry of the same
    upload lands in the same row instead of forking a duplicate pipeline.

    Returns the row dict, or None in dev/no-op mode.
    """
    supabase = _client_or_none(org_id)
    if supabase is None:
        return None
    row = {
        "org_id": org_id,
        "video_id": video_id,
        "video_title": video_title,
        "thread_id": thread_id,
        "status": status,
        "updated_at": _now_iso(),
    }
    resp = (
        supabase.table("content_pipelines")
        .upsert(row, on_conflict="org_id,video_id")
        .execute()
    )
    return resp.data[0] if resp.data else None


def record_stage(
    org_id: str,
    video_id: str,
    stage: str,
    stage_status: str,
    detail: str | None = None,
) -> None:
    """Write one stage's outcome into the row's `stages` jsonb ledger.

    Read-modify-write (no jsonb_set RPC) — the pipeline is the row's only
    writer and stages execute sequentially, so lost updates aren't a concern.
    """
    supabase = _client_or_none(org_id)
    if supabase is None:
        return
    resp = (
        supabase.table("content_pipelines")
        .select("stages")
        .eq("org_id", org_id)
        .eq("video_id", video_id)
        .limit(1)
        .execute()
    )
    stages = (resp.data[0].get("stages") if resp.data else None) or {}
    stages[stage] = {"status": stage_status, "detail": detail, "at": _now_iso()}
    (
        supabase.table("content_pipelines")
        .update({"stages": stages, "updated_at": _now_iso()})
        .eq("org_id", org_id)
        .eq("video_id", video_id)
        .execute()
    )


def set_pipeline_status(
    org_id: str,
    video_id: str,
    status: str,
    *,
    error: str | None = None,
    assets: list[dict] | None = None,
) -> None:
    """Advance the row's top-level lifecycle status (and optionally attach the
    generated assets / a failure reason)."""
    supabase = _client_or_none(org_id)
    if supabase is None:
        return
    patch: dict[str, Any] = {"status": status, "updated_at": _now_iso()}
    if error is not None:
        patch["error"] = error
    if assets is not None:
        patch["assets"] = assets
    if status == "published":
        patch["published_at"] = _now_iso()
    (
        supabase.table("content_pipelines")
        .update(patch)
        .eq("org_id", org_id)
        .eq("video_id", video_id)
        .execute()
    )


def fetch_recent_pipelines(org_id: str, limit: int = 7) -> list[dict]:
    """Most recent pipelines for the org, newest first. Empty in dev mode."""
    supabase = _client_or_none(org_id)
    if supabase is None:
        return []
    resp = (
        supabase.table("content_pipelines")
        .select("video_id, video_title, video_kind, status, stages, assets, error, detected_at, published_at")
        .eq("org_id", org_id)
        .order("detected_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data or []


# ── LLM tools ───────────────────────────────────────────────────────────────

@tool
def get_pipeline_status(limit: int = 7) -> str:
    """Get the status of the most recent content pipelines — one per detected
    YouTube upload — including each stage's progress, generated assets, and
    any errors. Use this to answer questions like "where's today's content?"
    or "did the podcast go out?"."""
    org_id = current_org_id.get() or ""
    rows = fetch_recent_pipelines(org_id, limit=max(1, min(int(limit or 7), 25)))
    if not rows:
        return (
            "No content pipelines found yet. Pipelines appear automatically "
            "when a new video lands on the connected YouTube channel."
        )
    lines: list[str] = []
    for r in rows:
        title = r.get("video_title") or r.get("video_id")
        line = f"- **{title}** — {r.get('status')}"
        if r.get("error"):
            line += f" (error: {r['error']})"
        stages = r.get("stages") or {}
        if stages:
            done = [s for s, v in stages.items() if (v or {}).get("status") == "done"]
            line += f" [{len(done)}/{len(stages)} stages done]"
        n_assets = len(r.get("assets") or [])
        if n_assets:
            line += f", {n_assets} asset(s)"
        lines.append(line)
    return "\n".join(lines)


def get_content_tools() -> list:
    return [get_pipeline_status]
