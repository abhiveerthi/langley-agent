"""
Opus Clip client — auto-generate short clips from a YouTube upload.

The Content Agent submits the freshly-detected video's URL as a clipping
project; Opus processes it server-side (minutes, not seconds) and exposes
the finished clips for download/review. The agent runs inside a background
pipeline task, so `wait_for_project` polls with a bounded timeout instead of
holding a connection open.

Gating mirrors the Higgsfield pattern: `is_configured()` checks
OPUSCLIP_API_KEY; network entry points raise `OpusClipUnavailable` without
it so the generate_clips stage degrades to "skipped — not configured"
instead of failing the pipeline. When the key is absent the team's Opus
workflow simply stays manual.

NOTE ON ENDPOINTS: Opus Clip's API is plan-gated (their API tier). Paths
and payload keys are isolated in constants + `_normalize_project` so
confirming the account's actual shape when a key lands is a contained fix —
callers only ever see the normalized {id, status, clips[]} contract.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

BASE_URL = "https://api.opus.pro/api/v1"
PROJECTS_PATH = "/projects"

# Terminal statuses in normalized form.
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_PROCESSING = "processing"

_DONE_RAW = {"done", "completed", "complete", "succeeded", "success", "finished"}
_FAILED_RAW = {"failed", "error", "canceled", "cancelled"}


class OpusClipUnavailable(RuntimeError):
    """Opus Clip isn't configured (no OPUSCLIP_API_KEY)."""


class OpusClipError(RuntimeError):
    """Opus Clip is configured but a call failed."""


class OpusClipTimeout(OpusClipError):
    """The project didn't reach a terminal status within the wait budget."""


def is_configured() -> bool:
    return bool(os.environ.get("OPUSCLIP_API_KEY"))


def _headers() -> dict[str, str]:
    key = os.environ.get("OPUSCLIP_API_KEY")
    if not key:
        raise OpusClipUnavailable(
            "Opus Clip isn't configured — set OPUSCLIP_API_KEY to enable "
            "automatic clip generation; the pipeline skips clips without it."
        )
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _normalize_status(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in _DONE_RAW:
        return STATUS_DONE
    if s in _FAILED_RAW:
        return STATUS_FAILED
    return STATUS_PROCESSING


def _normalize_project(payload: dict) -> dict:
    """Collapse plausible payload shapes onto the {id, status, clips[]}
    contract callers rely on. Each clip: {url, title, duration_seconds}."""
    proj = payload.get("project") if isinstance(payload.get("project"), dict) else payload
    clips_raw = proj.get("clips") or proj.get("outputs") or []
    clips: list[dict] = []
    for c in clips_raw:
        if not isinstance(c, dict):
            continue
        url = c.get("url") or c.get("video_url") or c.get("download_url")
        if not url:
            continue
        duration = c.get("duration_seconds") or c.get("duration")
        try:
            duration = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        clips.append({
            "url": url,
            "title": c.get("title") or c.get("name") or "",
            "duration_seconds": duration,
        })
    return {
        "id": proj.get("id") or proj.get("project_id"),
        "status": _normalize_status(proj.get("status") or proj.get("state")),
        "error": proj.get("error") or proj.get("failure_reason"),
        "clips": clips,
    }


async def submit_clip_project(video_url: str) -> dict:
    """Submit a video URL for clipping. Returns the normalized project (its
    status will typically be 'processing'; poll with wait_for_project)."""
    headers = _headers()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{BASE_URL}{PROJECTS_PATH}",
            json={"video_url": video_url},
            headers=headers,
        )
    if resp.status_code >= 400:
        raise OpusClipError(
            f"Opus Clip project submit failed: {resp.status_code} {resp.text[:300]}"
        )
    project = _normalize_project(resp.json() or {})
    if not project.get("id"):
        raise OpusClipError(f"Opus Clip submit returned no project id: {resp.text[:300]}")
    return project


async def get_project(project_id: str) -> dict:
    """Fetch one project's normalized state."""
    headers = _headers()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{BASE_URL}{PROJECTS_PATH}/{project_id}", headers=headers
        )
    if resp.status_code >= 400:
        raise OpusClipError(
            f"Opus Clip project fetch failed: {resp.status_code} {resp.text[:300]}"
        )
    return _normalize_project(resp.json() or {})


async def wait_for_project(
    project_id: str,
    *,
    timeout_seconds: int = 1800,
    poll_seconds: int = 30,
) -> dict:
    """Poll until the project is done/failed or the budget runs out.

    Runs inside the Content Agent's background pipeline task, so a long wait
    only occupies that task — the scheduler sweep is never blocked. Raises
    OpusClipTimeout past the budget and OpusClipError on a failed project.

    The budget is WALL-CLOCK (monotonic deadline), not a count of sleeps —
    a degraded Opus API whose polls each take ~30s must not stretch an
    1800s budget into ~3600s of real time.
    """
    import time

    deadline = time.monotonic() + timeout_seconds
    while True:
        project = await get_project(project_id)
        if project["status"] == STATUS_DONE:
            return project
        if project["status"] == STATUS_FAILED:
            raise OpusClipError(
                f"Opus Clip project {project_id} failed: {project.get('error') or 'unknown reason'}"
            )
        if time.monotonic() >= deadline:
            raise OpusClipTimeout(
                f"Opus Clip project {project_id} still processing after "
                f"{timeout_seconds}s — giving up this run; the project may "
                f"still finish in Opus and can be pulled on a retry."
            )
        await asyncio.sleep(poll_seconds)
