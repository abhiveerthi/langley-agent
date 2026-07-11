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


def _load_broll_config(supabase: Any, org_id: str) -> dict:
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
            return {}
        config = resp.data[0].get("config")
        return config if isinstance(config, dict) else {}
    except Exception:
        return {}


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

        try:
            job = (
                supabase.table("scheduled_jobs")
                .select("last_run_at")
                .eq("org_id", org_id)
                .eq("kind", JOB_KIND)
                .limit(1)
                .execute()
            )
            last_run_at = job.data[0].get("last_run_at") if job.data else None
        except Exception:
            log.exception("broll sweep: job lookup failed for org=%s", org_id)
            continue
        if not is_due(last_run_at):
            continue

        # Claim the day BEFORE the (long) run so the next sweep doesn't
        # double-fire; a failed run escalates rather than silently retrying
        # all day (rendering costs real money).
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            supabase.table("scheduled_jobs").upsert(
                {
                    "org_id": org_id,
                    "kind": JOB_KIND,
                    "enabled": True,
                    "interval_seconds": 86400,
                    "last_run_at": now_iso,
                    "updated_at": now_iso,
                },
                on_conflict="org_id,kind",
            ).execute()
        except Exception:
            log.exception("broll sweep: claim failed for org=%s", org_id)
            continue

        _inflight.add(org_id)
        task = asyncio.create_task(_run_wrapper(supabase, org_id))
        _tasks.add(task)

        def _done(t: asyncio.Task, org_id: str = org_id) -> None:
            _tasks.discard(t)
            _inflight.discard(org_id)

        task.add_done_callback(_done)


async def _run_wrapper(supabase: Any, org_id: str) -> None:
    try:
        summary = await run_daily_production(supabase, org_id)
        log.info("broll daily production org=%s: %s", org_id, summary)
    except Exception:
        log.exception("broll daily production crashed for org=%s", org_id)
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

    async def _produce(i: int, spec: dict) -> None:
        nonlocal deposited, failures
        async with sem:
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
                else:
                    failures += 1
            except Exception as e:
                failures += 1
                log.warning("broll clip %d failed for org=%s: %r", i, org_id, e)

    await asyncio.gather(*(_produce(i, s) for i, s in enumerate(specs)))
    return deposited, failures


async def run_daily_production(supabase: Any, org_id: str) -> str:
    """Draft → render → deposit one day's b-roll batch for one org."""
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
        config = _load_broll_config(supabase, org_id)
        direction = (config.get("weekly_direction") or "").strip() or (
            "Pro-America angles, sarcasm, and humor — varied interrupt-style "
            "beats: slapstick, sports misses, funny interruptions, dramatic stings."
        )
        try:
            target = int(config.get("daily_clip_target") or DEFAULT_DAILY_TARGET)
        except (TypeError, ValueError):
            target = DEFAULT_DAILY_TARGET
        target = max(1, min(target, MAX_DAILY_TARGET))
        default_aspect = str(config.get("default_aspect_ratio") or "16:9")

        # Cross-agent handoff: the Image Reader's recent filed analyses feed
        # the drafting prompt as inspiration.
        insights = await fetch_recent_image_insights(org_id)
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
