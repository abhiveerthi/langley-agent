"""
Background job-runner foundation + YouTube new-upload poller.

This is the scheduling layer behind Agent #5 ("Force Multiplier"): it watches
every org's connected YouTube channel for a new upload and, when one lands,
kicks off the existing Publisher `create_package` flow for that video — fully
automatically, no human in the loop until the package is ready for review.

## How it runs

`start_scheduler()` is called from the FastAPI lifespan (apps/api/app/main.py)
and spawns one long-lived asyncio task: `_poll_loop`. It sleeps
`settings.scheduler_poll_interval_seconds` (default 300s) between sweeps. The
loop is started ONLY when `settings.scheduler_enabled` is true — which defaults
False — so importing the app in tests or ad-hoc scripts never spins up a live
network loop. Production sets `SCHEDULER_ENABLED=true` in the deploy env.

`stop_scheduler()` (also from the lifespan) cancels the task on shutdown.

## Defensiveness

The loop must survive everything: one org's expired token, a YouTube 403, a
malformed integrations row. So:
  - Each org is polled inside its own try/except (`_poll_org`); a failure is
    recorded to `youtube_poll_state.last_error` and the sweep moves on.
  - The sweep itself is wrapped so a top-level error (e.g. Supabase
    unreachable) logs and waits for the next interval instead of killing the
    loop.

## New-upload decision

`is_new_upload(last_seen_video_id, latest_video_id)` is the pure, unit-tested
core: a video is "new" iff the API's latest upload id differs from the id we
last acted on (and is non-empty). First-ever poll of a channel (no
`last_seen_video_id`) does NOT fire Publisher — it just records the current
head so we don't blast a package for a back-catalog video on first boot.
`last_seen_video_id` is advanced after a successful dispatch so each upload
triggers exactly once.

## Dispatch

We reuse the orchestrator's `stream_new_run` with the identical state the
Publisher router sends for a manual "Package this video" click
(`intent=create_package`, `video_id`, `video_title`, `package_id`) — the
poller is just an automated caller of the same path, not a reimplementation
of agent running. The generator is drained to completion with the org's
tenancy ContextVars set, mirroring the router's `_run_in_background`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

log = logging.getLogger("scheduler")

# Module-level handle so `stop_scheduler` can cancel what `start_scheduler`
# spawned. None when the scheduler is disabled or not yet started.
_task: asyncio.Task | None = None


# ── Pure decision logic (unit-tested) ──────────────────────────────────────

def is_new_upload(last_seen_video_id: str | None, latest_video_id: str | None) -> bool:
    """Decide whether `latest_video_id` is an upload we haven't acted on yet.

    Rules:
      - No latest video (empty channel / failed lookup) → not new.
      - First-ever poll (`last_seen_video_id` is None/empty) → NOT new. We
        record the head instead of firing Publisher on a back-catalog video
        the moment the org connects.
      - Otherwise new iff the ids differ.
    """
    if not latest_video_id:
        return False
    if not last_seen_video_id:
        return False
    return latest_video_id != last_seen_video_id


# ── Supabase service-role client ────────────────────────────────────────────

def _service_client():
    """Build a service-role Supabase client for the runner.

    The poller has no request context, so it can't use the request-scoped
    dependency-injected client. Service role bypasses RLS, which is what we
    want — the runner legitimately reads every org's integration + poll state.
    Returns None when Supabase isn't configured (dev without a DB).
    """
    from app.config import get_settings
    from supabase import create_client

    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_key):
        return None
    return create_client(settings.supabase_url, settings.supabase_service_key)


# ── Per-org poll step ───────────────────────────────────────────────────────

async def _poll_org(supabase: Any, org_id: str) -> None:
    """Poll one org's YouTube channel and dispatch Publisher on a new upload.

    No-ops cleanly when YouTube isn't connected for the org (caller filters,
    but this re-checks). Records its outcome to `youtube_poll_state` so the
    next sweep has an accurate `last_seen_video_id` and any error is visible.
    """
    from datetime import datetime, timezone

    from app.config import get_settings
    from packages.integrations.youtube import client as yt

    settings = get_settings()

    conn = yt.get_connection(supabase, org_id)
    if not conn:
        return  # no YouTube connection — nothing to poll
    metadata = conn.get("metadata") or {}
    channel_id = metadata.get("channel_id")
    uploads_playlist_id = metadata.get("uploads_playlist_id")
    if not channel_id or not uploads_playlist_id:
        return  # connection row predates uploads_playlist_id capture

    now_iso = datetime.now(timezone.utc).isoformat()

    # Load prior poll state for this channel (service role; PK lookup).
    state_resp = (
        supabase.table("youtube_poll_state")
        .select("*")
        .eq("org_id", org_id)
        .eq("channel_id", channel_id)
        .limit(1)
        .execute()
    )
    state = state_resp.data[0] if state_resp.data else None
    last_seen = state.get("last_seen_video_id") if state else None

    try:
        access_token = await yt.get_fresh_access_token(
            supabase,
            org_id,
            settings.google_client_id,
            settings.google_client_secret,
        )
        latest = await yt.get_latest_upload(access_token, uploads_playlist_id)
    except Exception as e:
        log.warning("YouTube poll failed for org=%s: %r", org_id, e)
        _upsert_state(
            supabase, org_id, channel_id,
            last_seen_video_id=last_seen,
            last_polled_at=now_iso,
            last_error=str(e)[:500],
        )
        return

    latest_video_id = (latest or {}).get("video_id")

    if is_new_upload(last_seen, latest_video_id):
        log.info(
            "New upload detected for org=%s: %s (was %s) — dispatching Publisher",
            org_id, latest_video_id, last_seen,
        )
        try:
            await _dispatch_publisher(
                supabase, org_id,
                video_id=latest_video_id,
                video_title=(latest or {}).get("video_title") or latest_video_id,
            )
        except Exception as e:
            # Dispatch failed — DON'T advance last_seen, so the next sweep
            # retries this same upload instead of silently skipping it.
            log.exception("Publisher dispatch failed for org=%s video=%s", org_id, latest_video_id)
            _upsert_state(
                supabase, org_id, channel_id,
                last_seen_video_id=last_seen,
                last_polled_at=now_iso,
                last_error=f"dispatch failed: {e}"[:500],
            )
            return

    # Advance the head: on a successful dispatch, on a first-ever poll
    # (records the back-catalog head without firing), and on a no-change poll.
    _upsert_state(
        supabase, org_id, channel_id,
        last_seen_video_id=latest_video_id or last_seen,
        last_polled_at=now_iso,
        last_error=None,
    )


def _upsert_state(
    supabase: Any,
    org_id: str,
    channel_id: str,
    *,
    last_seen_video_id: str | None,
    last_polled_at: str,
    last_error: str | None,
) -> None:
    """Idempotent upsert of one channel's poll state (PK = org_id, channel_id)."""
    try:
        supabase.table("youtube_poll_state").upsert(
            {
                "org_id": org_id,
                "channel_id": channel_id,
                "last_seen_video_id": last_seen_video_id,
                "last_polled_at": last_polled_at,
                "last_error": last_error,
                "updated_at": last_polled_at,
            },
            on_conflict="org_id,channel_id",
        ).execute()
    except Exception as e:
        log.warning("youtube_poll_state upsert failed for org=%s: %r", org_id, e)


async def _dispatch_publisher(
    supabase: Any, org_id: str, *, video_id: str, video_title: str
) -> None:
    """Kick off the Publisher create_package flow for a freshly-detected video.

    Mirrors apps/api/app/routers/publisher.py::create_package: upsert a
    generating-status `publisher_packages` row, then drive the same
    `stream_new_run(intent=create_package, ...)` path the manual click uses.
    Runs the generator to completion here (the poller has no request lifecycle
    to outlive) with the org's tenancy ContextVars set so the Publisher's
    tools can reach the OAuth connection.

    user_id is None for poller-initiated runs — there's no human actor. The
    orchestrator + tools tolerate a null user_id (thread row just omits it).
    """
    from app.services.graph_orchestrator import stream_new_run
    from packages.integrations.context import (
        current_org_id,
        current_supabase,
        current_user_id,
    )

    # Upsert the package row (status=generating) so the UI surfaces it.
    existing = (
        supabase.table("publisher_packages")
        .select("id")
        .eq("org_id", org_id)
        .eq("video_id", video_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        package_id = existing.data[0]["id"]
        supabase.table("publisher_packages").update(
            {"status": "generating", "video_title": video_title}
        ).eq("id", package_id).execute()
    else:
        created = (
            supabase.table("publisher_packages")
            .insert(
                {
                    "org_id": org_id,
                    "video_id": video_id,
                    "video_title": video_title,
                    "status": "generating",
                }
            )
            .execute()
        )
        package_id = created.data[0]["id"]

    thread_id = str(uuid4())
    gen = stream_new_run(
        agent_slug="publisher",
        message=f"Package video {video_id}",
        thread_id=thread_id,
        org_id=org_id,
        user_id=None,  # auto-poll has no human actor
        extra_state={
            "intent": "create_package",
            "video_id": video_id,
            "video_title": video_title,
            "package_id": package_id,
        },
    )

    # Set tenancy ContextVars for the duration of the drain, then restore.
    org_tok = current_org_id.set(org_id)
    user_tok = current_user_id.set(None)
    sb_tok = current_supabase.set(supabase)
    try:
        async for _ in gen:
            pass
    finally:
        current_org_id.reset(org_tok)
        current_user_id.reset(user_tok)
        current_supabase.reset(sb_tok)


# ── Sweep + loop ────────────────────────────────────────────────────────────

async def poll_once(supabase: Any | None = None) -> None:
    """Run one full sweep across every org with a YouTube connection.

    Exposed (rather than inlined into the loop) so it can be invoked manually
    from a script or a future on-demand endpoint, and so the loop body stays
    a thin wrapper. Builds its own service-role client if one isn't passed.
    """
    if supabase is None:
        supabase = _service_client()
    if supabase is None:
        log.info("Scheduler sweep skipped — Supabase not configured")
        return

    # Org list = distinct org_ids with an active YouTube integration. Service
    # role read; the `integrations` unique(org_id, provider) means one row max.
    resp = (
        supabase.table("integrations")
        .select("org_id")
        .eq("provider", "youtube")
        .eq("status", "active")
        .execute()
    )
    org_ids = [r["org_id"] for r in (resp.data or []) if r.get("org_id")]
    log.info("Scheduler sweep: %d org(s) with active YouTube", len(org_ids))

    for org_id in org_ids:
        try:
            await _poll_org(supabase, org_id)
        except Exception:
            # Belt-and-braces: _poll_org already isolates its own errors, but
            # one org must never abort the sweep.
            log.exception("Unhandled error polling org=%s", org_id)


async def _poll_loop(interval_seconds: int) -> None:
    """Long-lived loop: sweep, sleep, repeat. Never dies on a transient error."""
    log.info("Scheduler loop started (interval=%ss)", interval_seconds)
    # Build the service client once and reuse it across sweeps.
    supabase = _service_client()
    while True:
        try:
            await poll_once(supabase)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Scheduler sweep failed; continuing")
        await asyncio.sleep(interval_seconds)


# ── Lifespan hooks ──────────────────────────────────────────────────────────

def start_scheduler() -> None:
    """Spawn the poll loop iff `settings.scheduler_enabled`. Idempotent.

    Called from the FastAPI lifespan. When disabled (the default — keeps tests
    and imports hermetic) this is a no-op and no task is created.
    """
    global _task
    from app.config import get_settings

    settings = get_settings()
    if not settings.scheduler_enabled:
        log.info("Scheduler disabled (SCHEDULER_ENABLED is false) — not starting loop")
        return
    if _task is not None and not _task.done():
        return  # already running
    _task = asyncio.create_task(
        _poll_loop(settings.scheduler_poll_interval_seconds)
    )


async def stop_scheduler() -> None:
    """Cancel the poll loop on shutdown. No-op if it was never started."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("Scheduler loop raised on shutdown")
    _task = None
