"""
B-Roll daily production — Agent #7's automation layer.

The B-Roll agent's chat lanes (draft / generate / regenerate on direction)
already exist; this module is what makes it a CONTINUOUS DAILY SUPPLY:
once per day, for every org that opted in, it drafts a full day's worth of
interrupt-style prompts from the creator's WEEKLY DIRECTION (agents.config
`weekly_direction`, refreshed by Braden at the top of the week via chat or
config), renders them through Higgsfield, and files every clip into
Dropbox under /B-Roll/<date>/<topic>/ — no human kickoff.

Volume: `daily_clip_target` (default 100, the product target) drafted in
LLM batches (~12 prompts each so variety stays high), rendered with
bounded concurrency. Per-clip failures are counted, never fatal; a mostly-
failed day escalates to the owner's Slack. A workspace task summarizing
the batch is filed so the day's output is visible outside Dropbox.

Once-per-day bookkeeping lives in the scheduled_jobs registry
(kind='broll_daily_production', one row per org — the table 017 laid down
for exactly this). The sweep runs from the scheduler's poll loop; actual
production runs as a tracked background task (a 100-clip day takes a
while and must never stall the sweep).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("broll_production")

JOB_KIND = "broll_daily_production"

DEFAULT_DAILY_TARGET = 100
MAX_DAILY_TARGET = 150
DRAFT_BATCH_SIZE = 12
GENERATION_CONCURRENCY = 3
# Abort the day after this many consecutive render/deposit failures — a
# systemic outage must not burn the whole batch one paid failure at a time.
CIRCUIT_BREAKER_FAILURES = 8
# Escalate when more than this fraction of the day's clips failed.
FAILURE_ESCALATION_RATIO = 0.5

_tasks: set[asyncio.Task] = set()
_inflight: set[str] = set()  # org_ids with a production run in flight


def is_due(last_run_at: str | None, *, now: datetime | None = None) -> bool:
    """One run per UTC day: due iff never run, or last run before today."""
    now = now or datetime.now(timezone.utc)
    if not last_run_at:
        return True
    try:
        last = datetime.fromisoformat(str(last_run_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return last.date() < now.date()


def _load_broll_config(supabase: Any, org_id: str) -> dict | None:
    """The org's b-roll config, or None when it CANNOT be read (query
    failure / inactive agent). None is deliberately distinct from {} — a
    transient DB error must abort the run, not silently fall back to
    defaults and render 100 clips with the wrong direction and volume."""
    try:
        resp = (
            supabase.table("agents")
            .select("config, active")
            .eq("org_id", org_id)
            .eq("slug", "broll")
            .limit(1)
            .execute()
        )
        if not resp.data or not resp.data[0].get("active"):
            return None
        config = resp.data[0].get("config")
        return config if isinstance(config, dict) else {}
    except Exception:
        return None


def _dropbox_ready(supabase: Any, org_id: str) -> bool:
    """Preflight: rendering costs real money, and deposit_clip_to_dropbox is
    best-effort (returns None, never raises) — without this check an org
    with production enabled but no Dropbox connection would burn a full
    day of renders into the void, every day."""
    import os

    if not (os.environ.get("DROPBOX_CLIENT_ID") and os.environ.get("DROPBOX_CLIENT_SECRET")):
        return False
    try:
        resp = (
            supabase.table("integrations")
            .select("status")
            .eq("org_id", org_id)
            .eq("provider", "dropbox")
            .limit(1)
            .execute()
        )
        return bool(resp.data and resp.data[0].get("status") == "active")
    except Exception:
        return False


def _claim_day(supabase: Any, org_id: str, *, now: datetime | None = None) -> bool:
    """Atomically claim today's run — safe across PROCESSES, not just tasks.

    Two API replicas (deploy overlap, scaled instances, staging+prod on one
    DB) can sweep concurrently; a read-then-upsert would let both claim and
    double-render ~100 paid clips. So the claim is a compare-and-swap:

      1. Conditional UPDATE where last_run_at < start-of-today — only ONE
         racer's update matches the stale row (PostgREST returns the
         updated rows; empty data = lost the race or already claimed).
      2. If no row matched and none exists, INSERT — the unique index on
         (org_id, kind) makes the second racer's insert fail.
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    today_start = f"{now.date().isoformat()}T00:00:00+00:00"

    try:
        resp = (
            supabase.table("scheduled_jobs")
            .update({"last_run_at": now_iso, "last_status": "running", "updated_at": now_iso})
            .eq("org_id", org_id)
            .eq("kind", JOB_KIND)
            .lt("last_run_at", today_start)
            .execute()
        )
        if resp.data:
            return True
    except Exception:
        log.exception("broll claim update failed for org=%s", org_id)
        return False

    # No stale row updated: either already claimed today, or no row yet.
    try:
        existing = (
            supabase.table("scheduled_jobs")
            .select("id")
            .eq("org_id", org_id)
            .eq("kind", JOB_KIND)
            .limit(1)
            .execute()
        )
        if existing.data:
            return False  # row exists and wasn't stale → claimed today
        supabase.table("scheduled_jobs").insert({
            "org_id": org_id,
            "kind": JOB_KIND,
            "enabled": True,
            "interval_seconds": 86400,
            "last_run_at": now_iso,
            "last_status": "running",
        }).execute()
        return True
    except Exception:
        # Insert lost the unique-index race, or the DB blipped — either way
        # this process must not render.
        log.warning("broll claim insert lost/failed for org=%s", org_id)
        return False


def _mark_run_result(supabase: Any, org_id: str, status: str, detail: str = "") -> None:
    try:
        supabase.table("scheduled_jobs").update({
            "last_status": status,
            "last_error": detail[:500] or None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("org_id", org_id).eq("kind", JOB_KIND).execute()
    except Exception:
        log.warning("broll run-result write failed for org=%s", org_id)


async def broll_daily_sweep(supabase: Any) -> None:
    """Called each scheduler sweep; fires at most one production run per
    org per UTC day. Cheap when nothing is due."""
    from packages.integrations import higgsfield

    if not higgsfield.is_configured():
        return  # no renderer — nothing to produce anywhere

    try:
        resp = (
            supabase.table("agents")
            .select("org_id, config")
            .eq("slug", "broll")
            .eq("active", True)
            .execute()
        )
        rows = resp.data or []
    except Exception:
        log.exception("broll sweep: agents query failed")
        return

    for row in rows:
        org_id = row.get("org_id")
        config = row.get("config") if isinstance(row.get("config"), dict) else {}
        if not org_id or not config.get("daily_production_enabled"):
            continue
        if org_id in _inflight:
            continue

        # Spend gates BEFORE claiming: no weekly direction means nothing to
        # draft against (and the old hardcoded fallback was one tenant's
        # politics baked into a multi-tenant service); no Dropbox means the
        # renders would be paid for and then discarded.
        if not (config.get("weekly_direction") or "").strip():
            log.info("broll sweep: org=%s has no weekly_direction — skipping", org_id)
            continue
        if not _dropbox_ready(supabase, org_id):
            log.info("broll sweep: org=%s has no active Dropbox — skipping", org_id)
            continue

        try:
            job = (
                supabase.table("scheduled_jobs")
                .select("last_run_at, enabled, last_status")
                .eq("org_id", org_id)
                .eq("kind", JOB_KIND)
                .limit(1)
                .execute()
            )
            job_row = job.data[0] if job.data else None
        except Exception:
            log.exception("broll sweep: job lookup failed for org=%s", org_id)
            continue

        if job_row is not None and job_row.get("enabled") is False:
            continue  # the migration-017 pause switch — respect it

        last_run_at = job_row.get("last_run_at") if job_row else None
        if job_row is not None and not is_due(last_run_at):
            # Claimed today. If the claim says "running" but is hours old,
            # the process died mid-run — surface it once (the documented
            # escalate-don't-retry recovery path must cover crashes too).
            if job_row.get("last_status") == "running" and _claim_is_stale(last_run_at):
                _mark_run_result(supabase, org_id, "died", "process died mid-run")
                from packages.agents.content.alerts import escalate

                await escalate(
                    org_id,
                    "B-roll daily production died mid-run (process restart?) — "
                    "today's batch is incomplete; rerun from chat if needed",
                    supabase=supabase,
                )
            continue

        # Atomic claim BEFORE the (long) run — see _claim_day for why this
        # must be a CAS and not an upsert.
        if not _claim_day(supabase, org_id):
            continue

        _inflight.add(org_id)
        task = asyncio.create_task(_run_wrapper(supabase, org_id, config))
        _tasks.add(task)

        def _done(t: asyncio.Task, org_id: str = org_id) -> None:
            _tasks.discard(t)
            _inflight.discard(org_id)

        task.add_done_callback(_done)


STALE_RUN_HOURS = 3


def _claim_is_stale(last_run_at: str | None) -> bool:
    from datetime import timedelta

    if not last_run_at:
        return False
    try:
        started = datetime.fromisoformat(str(last_run_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started > timedelta(hours=STALE_RUN_HOURS)


async def _run_wrapper(supabase: Any, org_id: str, config: dict) -> None:
    try:
        summary = await run_daily_production(supabase, org_id, config)
        log.info("broll daily production org=%s: %s", org_id, summary)
        _mark_run_result(supabase, org_id, "ok", summary)
    except Exception as e:
        log.exception("broll daily production crashed for org=%s", org_id)
        _mark_run_result(supabase, org_id, "failed", repr(e))
        try:
            from packages.agents.content.alerts import escalate

            await escalate(
                org_id,
                "B-roll daily production crashed — today's batch may be missing; "
                "check Higgsfield/Dropbox and rerun from chat if needed",
                supabase=supabase,
            )
        except Exception:
            pass


async def _draft_all(
    org_id: str, *, direction: str, insight_block: str, target: int, default_aspect: str
) -> list[dict]:
    """Draft `target` clip specs in variety-preserving batches."""
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import HumanMessage, SystemMessage

    from packages.agents.broll.agent import BRollAgent, BRollPlan
    from packages.agents.core.profile import load_profile
    from packages.agents.core.templates import render

    profile = load_profile(org_id)
    llm = ChatAnthropic(model=BRollAgent.model)
    structured = llm.with_structured_output(BRollPlan)
    system_prompt = render("broll", "draft_scripts.j2", profile=profile, peer_context={})

    specs: list[dict] = []
    while len(specs) < target:
        want = min(DRAFT_BATCH_SIZE, target - len(specs))
        try:
            plan: BRollPlan = await structured.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=(
                    f"This week's direction: {direction}{insight_block}\n\n"
                    f"Write exactly {want} clips. Default aspect ratio "
                    f"{default_aspect}. Today is batch part "
                    f"{len(specs) // DRAFT_BATCH_SIZE + 1}; avoid repeating "
                    f"beats you'd expect in earlier parts — push variety."
                )),
            ])
        except Exception as e:
            # One transient LLM failure must not silently kill the whole
            # day — keep whatever was already drafted; the caller reports
            # the shortfall.
            log.warning("broll draft batch failed for org=%s: %r", org_id, e)
            break
        batch = [c.model_dump() for c in (plan.clips or [])]
        if not batch:
            break
        specs.extend(batch[:want])
    return specs


async def _render_and_deposit(
    org_id: str, specs: list[dict], *, default_aspect: str
) -> tuple[int, int]:
    """Render every spec through Higgsfield and file it in Dropbox.
    Returns (deposited, failures); per-clip failures never abort the day."""
    from packages.agents.broll.tools import deposit_clip_to_dropbox
    from packages.integrations import higgsfield

    sem = asyncio.Semaphore(GENERATION_CONCURRENCY)
    deposited = 0
    failures = 0
    consecutive_failures = 0
    aborted = False

    async def _produce(i: int, spec: dict) -> None:
        nonlocal deposited, failures, consecutive_failures, aborted
        async with sem:
            # Circuit breaker: a systemic outage (Higgsfield down, Dropbox
            # token revoked) must not burn the remaining ~90 paid renders
            # one failure at a time.
            if aborted:
                failures += 1
                return
            try:
                clip = await higgsfield.generate_clip(
                    spec.get("prompt", ""),
                    aspect_ratio=spec.get("aspect_ratio") or default_aspect,
                    duration_seconds=int(spec.get("duration_seconds") or 6),
                    download=True,
                )
                if not clip.bytes_:
                    raise RuntimeError("no clip bytes returned")
                aspect = (clip.aspect_ratio or "16-9").replace(":", "-")
                path = await deposit_clip_to_dropbox(
                    org_id,
                    filename=f"{i:03d}-{aspect}-clip.mp4",
                    clip_bytes=clip.bytes_,
                    topic=spec.get("topic") or "misc",
                )
                if path:
                    deposited += 1
                    consecutive_failures = 0
                else:
                    failures += 1
                    consecutive_failures += 1
            except Exception as e:
                failures += 1
                consecutive_failures += 1
                log.warning("broll clip %d failed for org=%s: %r", i, org_id, e)
            if consecutive_failures >= CIRCUIT_BREAKER_FAILURES:
                aborted = True

    await asyncio.gather(*(_produce(i, s) for i, s in enumerate(specs)))
    if aborted:
        log.warning(
            "broll production aborted early for org=%s after %d consecutive failures",
            org_id, CIRCUIT_BREAKER_FAILURES,
        )
    return deposited, failures


async def run_daily_production(supabase: Any, org_id: str, config: dict) -> str:
    """Draft → render → deposit one day's b-roll batch for one org.

    `config` comes from the SWEEP's read (the same one that decided this
    org was eligible) — no second read here, so a transient DB blip between
    sweep and run can't swap the org's direction/target for defaults."""
    from packages.agents.broll.tools import fetch_recent_image_insights
    from packages.agents.core.tasks import create_task_from_agent
    from packages.integrations.context import (
        current_org_id,
        current_supabase,
        current_user_id,
    )

    org_tok = current_org_id.set(org_id)
    user_tok = current_user_id.set(None)
    sb_tok = current_supabase.set(supabase)
    try:
        # The sweep guarantees a direction exists; re-check defensively.
        # There is deliberately NO fallback direction — a generic default
        # would render 100 clips of content nobody asked for.
        direction = (config.get("weekly_direction") or "").strip()
        if not direction:
            return "no weekly_direction configured — nothing rendered"

        try:
            target = int(config.get("daily_clip_target") or DEFAULT_DAILY_TARGET)
        except (TypeError, ValueError):
            target = DEFAULT_DAILY_TARGET
        target = max(1, min(target, MAX_DAILY_TARGET))
        default_aspect = str(config.get("default_aspect_ratio") or "16:9")

        # Cross-agent handoff: the Image Reader's recent filed analyses feed
        # the drafting prompt as inspiration. Optional — never fatal.
        try:
            insights = await fetch_recent_image_insights(org_id)
        except Exception as e:
            log.warning("broll insight feed failed for org=%s: %r", org_id, e)
            insights = []
        insight_block = (
            "\n\nRecent visual research from the Image Reader (use as inspiration "
            "where it fits):\n" + "\n".join(f"- {i}" for i in insights)
            if insights else ""
        )

        specs = await _draft_all(
            org_id, direction=direction, insight_block=insight_block,
            target=target, default_aspect=default_aspect,
        )
        if not specs:
            # Zero drafted specs is a broken day, not a quiet no-op — the
            # owner expects ~target clips waiting in Dropbox.
            from packages.agents.content.alerts import escalate

            await escalate(
                org_id,
                "B-roll daily production drafted zero clips (LLM failure or "
                "refused direction) — no batch today; check the weekly "
                "direction or rerun from chat",
                supabase=supabase,
            )
            return "drafting produced no clip specs — nothing rendered"

        deposited, failures = await _render_and_deposit(
            org_id, specs, default_aspect=default_aspect
        )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        summary = f"{deposited}/{len(specs)} clips deposited to /B-Roll/{today}/ ({failures} failed)"

        await create_task_from_agent(
            org_id=org_id,
            agent_slug="broll",
            title=f"B-roll batch {today}: {deposited} clips ready",
            description=(
                f"Daily production run: {summary}.\n"
                f"Direction: {direction[:300]}"
            ),
            metadata={"kind": "broll_daily_batch", "date": today},
        )

        if failures and failures / len(specs) > FAILURE_ESCALATION_RATIO:
            from packages.agents.content.alerts import escalate

            await escalate(
                org_id,
                f"B-roll daily production mostly failed: {summary}. "
                f"Higgsfield or Dropbox likely needs attention.",
                supabase=supabase,
            )
        return summary
    finally:
        current_org_id.reset(org_tok)
        current_user_id.reset(user_tok)
        current_supabase.reset(sb_tok)
