"""
Content Agent (Agent #5) dispatch + publish orchestration.

Split out of scheduler.py (which owns the poll loop and the Publisher
dispatch): everything here is the Content Agent's slice of the background
runtime —

  - _dispatch_content / _run_content_pipeline: fire the repurposing
    pipeline for a freshly-detected upload as a tracked background task,
    with an in-flight guard and a post-drain stuck-check.
  - _publish_catchup / _rescue_stale_publishing: the sweep-time safety
    nets for the publish fan-out (retry `approved`, un-wedge `publishing`).
  - _mark_failed_if_stuck: the shared "ledger must never lie" guard.

scheduler.py re-exports these names so its tests (and _poll_org's
module-global lookups) keep working; the module boundary is about file
size and ownership, not behavior.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

log = logging.getLogger("scheduler")


def _content_agent_active(supabase: Any, org_id: str) -> bool:
    """Is the Content Agent (Agent #5) enabled for this org?

    Reads the org's `agents` row for slug `content` — the same active flag
    that gates @mention autocomplete. Off (or query failure) → the poller
    only fires Publisher, exactly the pre-Agent-#5 behaviour.
    """
    try:
        resp = (
            supabase.table("agents")
            .select("active")
            .eq("org_id", org_id)
            .eq("slug", "content")
            .limit(1)
            .execute()
        )
        return bool(resp.data and resp.data[0].get("active"))
    except Exception as e:
        log.warning("content-agent active check failed for org=%s: %r", org_id, e)
        return False


# Strong refs to in-flight content pipeline tasks (asyncio only keeps weak
# refs; without this a running pipeline could be garbage-collected mid-run).
_content_tasks: set[asyncio.Task] = set()

# (org_id, video_id) keys with a pipeline task currently running. Guards the
# re-sweep race: if the poll-state upsert fails transiently, last_seen never
# advances and the next sweep re-dispatches the same video while the first
# pipeline (legitimately minutes-long) is still in flight — without this
# guard that forks a second concurrent graph run against the same ledger row.
_content_inflight: set[tuple[str, str]] = set()


async def _dispatch_content(
    supabase: Any,
    org_id: str,
    *,
    video_id: str,
    video_title: str,
    published_at: str | None = None,
) -> None:
    """Kick off the Content Agent repurposing pipeline for a new upload.

    Pre-creates the `content_pipelines` ledger row (status=detected) so the
    dashboard shows the video the moment it's spotted — then runs the
    pipeline as a BACKGROUND task. Unlike the Publisher dispatch (seconds),
    a content pipeline legitimately runs for many minutes (Opus Clip
    processing, transcription of a 55-minute stream) and must not stall the
    poll sweep; failures land in the pipeline ledger, not the poll state.
    The row upsert is keyed on (org_id, video_id), so a retried dispatch
    re-enters the same pipeline instead of forking a duplicate. Tasks die
    with the process on shutdown — the ledger row shows where they stopped.
    """
    key = (org_id, video_id)
    if key in _content_inflight:
        log.info(
            "Content pipeline already in flight for org=%s video=%s — skipping duplicate dispatch",
            org_id, video_id,
        )
        return

    thread_id = str(uuid4())
    supabase.table("content_pipelines").upsert(
        {
            "org_id": org_id,
            "video_id": video_id,
            "video_title": video_title,
            "thread_id": thread_id,
            "status": "detected",
        },
        on_conflict="org_id,video_id",
    ).execute()

    _content_inflight.add(key)
    task = asyncio.create_task(
        _run_content_pipeline(
            supabase, org_id,
            video_id=video_id,
            video_title=video_title,
            published_at=published_at,
            thread_id=thread_id,
        )
    )
    _content_tasks.add(task)

    def _done(t: asyncio.Task, key: tuple[str, str] = key) -> None:
        _content_tasks.discard(t)
        _content_inflight.discard(key)

    task.add_done_callback(_done)


async def _run_content_pipeline(
    supabase: Any,
    org_id: str,
    *,
    video_id: str,
    video_title: str,
    published_at: str | None,
    thread_id: str,
) -> None:
    """Drive one content pipeline run to completion (background task body).

    Mirrors `_dispatch_publisher`'s drain-with-ContextVars pattern.

    Failure surfacing is a POST-DRAIN LEDGER CHECK, not just the except
    block: the orchestrator converts graph exceptions into SSE "error"
    events and ends the stream normally, so a crashed node never raises out
    of the drain loop. Whatever went wrong — raised here or swallowed there —
    a run that ends without the ledger reaching a terminal/reviewable status
    gets marked failed, so the dashboard never shows a silently-stuck
    'detected'/'processing' pipeline. The check never DOWNGRADES: a row
    already at ready_for_review (or beyond) is left alone even if the run's
    tail end errored after queue_review.
    """
    from app.services.graph_orchestrator import stream_new_run
    from packages.integrations.context import (
        current_org_id,
        current_supabase,
        current_user_id,
    )

    gen = stream_new_run(
        agent_slug="content",
        message=f"Process new upload {video_id}",
        thread_id=thread_id,
        org_id=org_id,
        user_id=None,  # auto-poll has no human actor
        extra_state={
            "intent": "run_pipeline",
            "video_id": video_id,
            "video_title": video_title,
            "published_at": published_at,
        },
    )

    org_tok = current_org_id.set(org_id)
    user_tok = current_user_id.set(None)
    sb_tok = current_supabase.set(supabase)
    run_error: str | None = None
    try:
        async for _ in gen:
            pass
    except Exception as e:
        log.exception("Content pipeline run failed for org=%s video=%s", org_id, video_id)
        run_error = f"pipeline run error: {e}"
    finally:
        current_org_id.reset(org_tok)
        current_user_id.reset(user_tok)
        current_supabase.reset(sb_tok)

    _mark_failed_if_stuck(
        supabase, org_id, video_id,
        reason=run_error or "pipeline run ended without completing its stages",
    )


def _mark_failed_if_stuck(
    supabase: Any, org_id: str, video_id: str, *, reason: str
) -> None:
    """If the pipeline row is still in a non-terminal pre-review status after
    its run ended, mark it failed. Guarded so a row that legitimately reached
    ready_for_review (or later) is never regressed by a late error."""
    try:
        resp = (
            supabase.table("content_pipelines")
            .select("status")
            .eq("org_id", org_id)
            .eq("video_id", video_id)
            .limit(1)
            .execute()
        )
        status = resp.data[0].get("status") if resp.data else None
        if status in ("detected", "processing"):
            supabase.table("content_pipelines").update(
                {"status": "failed", "error": reason[:500]}
            ).eq("org_id", org_id).eq("video_id", video_id).execute()
    except Exception:
        log.exception("Failed stuck-pipeline check for org=%s video=%s", org_id, video_id)


# ── Sweep + loop ────────────────────────────────────────────────────────────


# In-flight publish tasks, keyed like the content pipelines (see
# _content_inflight). CAS-claiming makes double-runs harmless; this guard
# just avoids stacking pointless tasks sweep after sweep.
_publish_inflight: set[tuple[str, str]] = set()

# A row sitting at `publishing` longer than this is a died run (the process
# restarted mid fan-out, or both _finish writes failed). Generous: a
# legitimate fan-out is bounded by download caps + upload/ingest timeouts.
STALE_PUBLISHING_MINUTES = 45


async def _publish_catchup(supabase: Any, limit: int = 10) -> None:
    """Two safety nets for the publish flow, run each sweep:

    1. Retry pipelines at `approved` (crash between approval and publish,
       or owner re-approval after a failure — no webhook fires for those).
       Runs as BACKGROUND tasks: one fan-out can legitimately take many
       minutes and must not stall the org poll sweep. run_publish's CAS
       claim (approved → publishing) makes webhook + sweep race-safe.
    2. Rescue rows wedged at `publishing` (a publish run died mid-flight):
       flip them to `failed` + escalate, which re-arms the owner's
       re-approve-to-retry loop — otherwise they'd be stuck forever
       (catch-up only claims `approved`, and the FINAL gate deliberately
       ignores flips while `publishing`).
    """
    from packages.agents.content.publish import run_publish

    resp = (
        supabase.table("content_pipelines")
        .select("org_id, video_id")
        .eq("status", "approved")
        .limit(limit)
        .execute()
    )
    for row in resp.data or []:
        org_id, video_id = row.get("org_id"), row.get("video_id")
        if not org_id or not video_id:
            continue
        key = (org_id, f"publish:{video_id}")
        if key in _publish_inflight:
            continue
        _publish_inflight.add(key)

        async def _run(org_id=org_id, video_id=video_id):
            try:
                summary = await run_publish(supabase, org_id, video_id)
                log.info("Publish catch-up org=%s video=%s: %s", org_id, video_id, summary)
            except Exception:
                log.exception("Publish catch-up crashed for org=%s video=%s", org_id, video_id)

        task = asyncio.create_task(_run())
        _content_tasks.add(task)

        def _done(t: asyncio.Task, key: tuple[str, str] = key) -> None:
            _content_tasks.discard(t)
            _publish_inflight.discard(key)

        task.add_done_callback(_done)

    await _rescue_stale_publishing(supabase)


async def _rescue_stale_publishing(supabase: Any, limit: int = 20) -> None:
    from datetime import datetime, timedelta, timezone

    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=STALE_PUBLISHING_MINUTES)
    ).isoformat()
    resp = (
        supabase.table("content_pipelines")
        .select("org_id, video_id, updated_at")
        .eq("status", "publishing")
        .lt("updated_at", cutoff)
        .limit(limit)
        .execute()
    )
    for row in resp.data or []:
        org_id, video_id = row.get("org_id"), row.get("video_id")
        if not org_id or not video_id:
            continue
        error = (
            f"publish run died mid-flight (stuck at publishing for over "
            f"{STALE_PUBLISHING_MINUTES}min) — re-approve the FINAL item to retry"
        )
        try:
            supabase.table("content_pipelines").update(
                {"status": "failed", "error": error}
            ).eq("org_id", org_id).eq("video_id", video_id).eq(
                "status", "publishing"
            ).execute()
            log.warning("Rescued stale publishing pipeline org=%s video=%s", org_id, video_id)
            from packages.agents.content.alerts import escalate

            await escalate(
                org_id,
                f"publish run for video {video_id} died mid-flight; "
                f"re-approve the FINAL item in Monday to retry",
                supabase=supabase,
            )
        except Exception:
            log.exception("Stale-publishing rescue failed for org=%s video=%s", org_id, video_id)
