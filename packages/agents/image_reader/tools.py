"""
Image Reader tools + research-report helpers.

`get_image_reader_tools()` now registers ONE LLM-callable tool:

  delegate_task — the "middle man" role from the product spec: after
      reading an image or hearing a voice note, the Image Reader can hand
      follow-up work to any other agent in the suite (a task lands on the
      workspace board attributed to that agent). Read-only analysis stays
      instant; the delegation is a lightweight task write, not an agent run.

The report-window helpers back the `compile_report` intent ("accumulate
daily data, then generate a detailed report for a 30–60 day window"):
every image analysis is filed to Storage as kind="report" with
source="image-reader", so a windowed research report is a query over that
archive plus one synthesis pass. All best-effort in dev mode.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool

from packages.agents.core.peer_context import _is_real_uuid
from packages.integrations.context import current_org_id, current_supabase

# Agents the Image Reader may delegate to. A fixed roster (not the live
# registry) so the LLM can't address non-agent slugs; keep in sync with
# packages/agents/registry.py.
DELEGATABLE_AGENTS = {
    "strategist", "publisher", "community-manager", "brand-manager",
    "broll", "content",
}

# compile_report window bounds: shorter than a week isn't a "window", and
# past ~90 days the archive query + prompt stop being useful.
MIN_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 90
DEFAULT_WINDOW_DAYS = 30

MAX_REPORTS_PER_WINDOW = 60
MAX_REPORT_CHARS = 200_000


def parse_window_days(text: str | None) -> int:
    """'give me the 60 day report' → 60; default 30; clamped 7–90."""
    m = re.search(r"\b(\d{1,3})\s*[- ]?\s*day", (text or "").lower())
    if not m:
        return DEFAULT_WINDOW_DAYS
    return max(MIN_WINDOW_DAYS, min(int(m.group(1)), MAX_WINDOW_DAYS))


@tool
async def delegate_task(agent_slug: str, instruction: str) -> str:
    """Hand a follow-up task to another agent on the team. Use when what you
    read or heard calls for another specialist's work — e.g. after reading a
    competitor screenshot: delegate_task('strategist', 'Fold the competitor
    momentum from today's screenshot into this week's brief'). Valid agents:
    strategist, publisher, community-manager, brand-manager, broll, content.
    Returns a confirmation or the reason the delegation was skipped."""
    from packages.agents.core.tasks import create_task_from_agent

    slug = (agent_slug or "").strip().lower()
    if slug not in DELEGATABLE_AGENTS:
        return (
            f"'{agent_slug}' isn't a delegatable agent. Choose one of: "
            + ", ".join(sorted(DELEGATABLE_AGENTS))
        )
    instruction = (instruction or "").strip()
    if not instruction:
        return "No instruction given — say what the agent should do."

    task_id = await create_task_from_agent(
        org_id=current_org_id.get(),
        agent_slug=slug,
        title=instruction[:120],
        description=instruction,
        metadata={"delegated_by": "image-reader"},
    )
    if task_id:
        return f"Delegated to {slug}: task {task_id} created."
    return "Couldn't create the task (no workspace context) — noted, but nothing was filed."


def get_image_reader_tools():
    return [delegate_task]


# ── Research-report archive helpers (compile_report intent) ────────────────

def fetch_recent_image_reports(org_id: str, days: int) -> list[dict]:
    """storage_assets rows for this agent's filed analyses inside the
    window, oldest first (reports read chronologically). Empty in dev."""
    supabase = current_supabase.get()
    if supabase is None or not _is_real_uuid(org_id):
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        resp = (
            supabase.table("storage_assets")
            .select("storage_path, filename, created_at")
            .eq("org_id", org_id)
            .eq("source", "image-reader")
            .eq("kind", "report")
            .eq("mime_type", "text/markdown")
            .gte("created_at", cutoff)
            # NEWEST first so the row cap drops the oldest analyses, not the
            # most recent ones; reversed below for chronological reading.
            .order("created_at", desc=True)
            .limit(MAX_REPORTS_PER_WINDOW)
            .execute()
        )
        rows = list(reversed(resp.data or []))
        # Compiled research reports are themselves filed with this exact
        # (source, kind, mime) signature — exclude them or every compilation
        # would ingest the previous ones (self-recursion / double counting).
        return [
            r for r in rows
            if not (r.get("filename") or "").startswith("research-report-")
        ]
    except Exception:
        return []


async def download_report_texts(rows: list[dict]) -> list[str]:
    """Pull each filed report's Markdown from the bucket, bounded by a
    total char budget so a dense archive can't blow the prompt."""
    supabase = current_supabase.get()
    if supabase is None:
        return []

    texts: list[str] = []
    total = 0
    for row in rows:
        path = row.get("storage_path")
        if not path:
            continue
        try:
            data = await asyncio.to_thread(
                supabase.storage.from_("org-assets").download, path
            )
        except Exception:
            continue
        text = data.decode("utf-8", errors="replace")
        stamp = (row.get("created_at") or "")[:10]
        entry = f"--- report filed {stamp} ---\n{text.strip()}"
        if total + len(entry) > MAX_REPORT_CHARS:
            break
        texts.append(entry)
        total += len(entry)
    return texts
