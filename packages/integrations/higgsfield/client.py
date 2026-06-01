"""
Higgsfield video-generation client.

Submits a text prompt to Higgsfield, polls the job to completion, and returns
the rendered b-roll clip (URL + bytes). Used by the B-Roll Producer agent to
turn AI-written b-roll scripts into short interrupt-style clips.

KEY-GATED + GRACEFUL DEGRADATION
--------------------------------
Activates only when HIGGSFIELD_API_KEY is set. With no key, every entry point
raises `HiggsfieldUnavailable` — a clear, catchable signal the agent turns into
a "video generation isn't configured yet" status message. This mirrors how the
rest of the codebase signals "not connected" (clients.py raises ValueError /
the integrations layer raises RuntimeError) rather than silently no-op'ing, so
the caller can surface an honest status. The SCRIPT-DRAFTING half of the agent
never touches this module, so prompt-writing works with no key at all.

ENDPOINT SHAPE (may need adjustment once we have API docs)
----------------------------------------------------------
We don't have confirmed Higgsfield REST docs yet, so this implements against a
sensible generic job-submit + poll shape, with every endpoint/path isolated as
a constant below. When the real docs land, adjust the constants and the small
response-field accessors (`_extract_job_id`, `_extract_status`,
`_extract_clip_url`) — the agent-facing contract (generate_clip ->
GeneratedClip) stays stable.

    POST {BASE}/v1/generations      {prompt, aspect_ratio, duration}  -> {id}
    GET  {BASE}/v1/generations/{id}                                   -> {status, output:{video_url}}
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import httpx

# ── Endpoint constants (ADJUST when real Higgsfield API docs are available) ──
HIGGSFIELD_API_BASE = os.environ.get("HIGGSFIELD_API_BASE", "https://api.higgsfield.ai")
_SUBMIT_PATH = "/v1/generations"
_STATUS_PATH = "/v1/generations/{job_id}"

# Terminal status strings we treat as success / failure. The real API may use
# different vocabulary — keep these as the single place to remap.
_SUCCESS_STATES = {"completed", "succeeded", "success", "done", "ready"}
_FAILURE_STATES = {"failed", "error", "cancelled", "canceled"}

# Supported output aspect ratios. 16:9 is primary (landscape), 9:16 is for
# YouTube Shorts (portrait).
ASPECT_RATIOS = ("16:9", "9:16")

_DEFAULT_POLL_INTERVAL = 5.0   # seconds between status polls
_DEFAULT_TIMEOUT = 600.0       # max seconds to wait for a single clip


class HiggsfieldError(RuntimeError):
    """A Higgsfield API call failed (HTTP error, generation failure, timeout)."""


class HiggsfieldUnavailable(HiggsfieldError):
    """Higgsfield is not configured (no HIGGSFIELD_API_KEY).

    Distinct subclass so the agent can catch "not configured" specifically and
    degrade gracefully — distinct from a real generation failure.
    """


@dataclass
class GeneratedClip:
    """A rendered b-roll clip returned by Higgsfield."""
    job_id: str
    url: str
    aspect_ratio: str
    duration_seconds: int
    prompt: str
    bytes_: bytes | None = None  # populated only when download=True


def is_configured() -> bool:
    """True when an API key is present so generation can be attempted."""
    return bool(os.environ.get("HIGGSFIELD_API_KEY"))


def _api_key() -> str:
    key = os.environ.get("HIGGSFIELD_API_KEY")
    if not key:
        raise HiggsfieldUnavailable(
            "HIGGSFIELD_API_KEY is not set — video generation is not configured. "
            "Add the key to .env to enable Higgsfield b-roll rendering."
        )
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


# ── Response-field accessors (ADJUST to match the real API response shape) ───
def _extract_job_id(payload: dict) -> str:
    job_id = payload.get("id") or payload.get("job_id") or payload.get("generation_id")
    if not job_id:
        raise HiggsfieldError(f"Higgsfield submit response had no job id: {payload!r}")
    return str(job_id)


def _extract_status(payload: dict) -> str:
    return str(payload.get("status") or payload.get("state") or "").lower()


def _extract_clip_url(payload: dict) -> str | None:
    output = payload.get("output") or payload.get("result") or {}
    if isinstance(output, dict):
        return output.get("video_url") or output.get("url") or output.get("clip_url")
    if isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, dict):
            return first.get("video_url") or first.get("url")
        if isinstance(first, str):
            return first
    return payload.get("video_url") or payload.get("url")


async def submit_generation(
    prompt: str,
    *,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 6,
) -> str:
    """Submit a generation job; return the Higgsfield job id.

    Raises HiggsfieldUnavailable if no key, HiggsfieldError on HTTP failure.
    """
    if aspect_ratio not in ASPECT_RATIOS:
        raise HiggsfieldError(
            f"Unsupported aspect_ratio {aspect_ratio!r}; use one of {ASPECT_RATIOS}"
        )
    body = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": duration_seconds,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{HIGGSFIELD_API_BASE}{_SUBMIT_PATH}",
            json=body,
            headers=_headers(),
        )
    if resp.status_code >= 400:
        raise HiggsfieldError(
            f"Higgsfield submit failed: {resp.status_code} {resp.text}"
        )
    return _extract_job_id(resp.json() or {})


async def poll_generation(
    job_id: str,
    *,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str:
    """Poll a job until it completes; return the rendered clip URL.

    Raises HiggsfieldError on a failed job or if `timeout` elapses first.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            resp = await client.get(
                f"{HIGGSFIELD_API_BASE}{_STATUS_PATH.format(job_id=job_id)}",
                headers=_headers(),
            )
            if resp.status_code >= 400:
                raise HiggsfieldError(
                    f"Higgsfield status check failed: {resp.status_code} {resp.text}"
                )
            payload = resp.json() or {}
            status = _extract_status(payload)
            if status in _SUCCESS_STATES:
                url = _extract_clip_url(payload)
                if not url:
                    raise HiggsfieldError(
                        f"Higgsfield job {job_id} completed without a clip URL: {payload!r}"
                    )
                return url
            if status in _FAILURE_STATES:
                err = payload.get("error") or payload.get("failure_reason") or status
                raise HiggsfieldError(f"Higgsfield job {job_id} failed: {err}")
            if asyncio.get_event_loop().time() >= deadline:
                raise HiggsfieldError(
                    f"Higgsfield job {job_id} did not finish within {timeout:.0f}s"
                )
            await asyncio.sleep(poll_interval)


async def download_clip(url: str) -> bytes:
    """Fetch the rendered clip bytes from its URL."""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url)
    if resp.status_code >= 400:
        raise HiggsfieldError(f"Higgsfield clip download failed: {resp.status_code}")
    return resp.content


async def generate_clip(
    prompt: str,
    *,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 6,
    download: bool = True,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
    timeout: float = _DEFAULT_TIMEOUT,
) -> GeneratedClip:
    """End-to-end: submit a prompt, await the rendered clip, optionally download.

    This is the agent-facing entry point. Returns a GeneratedClip with the
    job id, clip URL, and (when download=True) the raw bytes ready to deposit
    into Dropbox.

    Raises HiggsfieldUnavailable when no API key is configured (the agent
    catches this and reports "not configured yet"), or HiggsfieldError on a
    real generation failure / timeout. Re-running a bad clip is just calling
    this again with the same (or a tweaked) prompt.
    """
    # _api_key() inside the calls raises HiggsfieldUnavailable early if unset.
    job_id = await submit_generation(
        prompt, aspect_ratio=aspect_ratio, duration_seconds=duration_seconds
    )
    url = await poll_generation(job_id, poll_interval=poll_interval, timeout=timeout)
    raw = await download_clip(url) if download else None
    return GeneratedClip(
        job_id=job_id,
        url=url,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        prompt=prompt,
        bytes_=raw,
    )
