"""
Higgsfield video-generation client (platform.higgsfield.ai).

Submits a text prompt, polls the request to completion, and returns the
rendered b-roll clip (URL + bytes). Used by the B-Roll Producer agent to
turn AI-written b-roll scripts into short interrupt-style clips.

VERIFIED API CONTRACT (docs.higgsfield.ai + both official SDKs, July 2026)
--------------------------------------------------------------------------
  Auth:    ONE header — `Authorization: Key {api_key}:{api_secret}` (the
           literal word "Key"). Keys are issued as a PAIR at
           cloud.higgsfield.ai/api-keys; both parts are required.
  Submit:  POST https://platform.higgsfield.ai/{model_id}   (model_id is a
           slash path, e.g. bytedance/seedance/v1/lite/text-to-video) with
           a FLAT JSON body: {"prompt", "aspect_ratio", "duration", ...}.
           200 → {"status": "queued", "request_id": ..., "status_url": ...}
  Poll:    GET /requests/{request_id}/status
           Statuses: queued | in_progress | completed | failed | nsfw |
           canceled. Anything unrecognized is treated as NON-terminal
           (poll on until timeout) — the vocabulary has grown before.
           completed → result under "video": {"url": ...} (image models
           use "images": [{"url": ...}] — extractor tries both).
  Errors:  401 bad credentials · 403 = OUT OF API CREDITS (separate pool
           from the web subscription; top up at cloud.higgsfield.ai/credits)
           · 422 validation (Pydantic-style `detail`).

Operational notes for the daily batch:
  - Result URLs are only guaranteed ~7 days — callers must download and
    archive immediately (generate_clip(download=True) does).
  - `nsfw` is a moderation terminal state, auto-refunded — surfaced with
    its own message; retrying the SAME prompt is pointless.
  - failed/timeout are auto-refunded by Higgsfield.
  - Text-to-video model IDs aren't first-party-documented; the default
    below came from the platform OpenAPI capture and is env-overridable
    (HIGGSFIELD_T2V_MODEL) — verify with one real call before a full batch.

KEY-GATED + GRACEFUL DEGRADATION: activates only when BOTH
HIGGSFIELD_API_KEY and HIGGSFIELD_API_SECRET are set; otherwise every
entry point raises HiggsfieldUnavailable and the agent reports "not
configured" instead of failing. Script drafting never touches this module.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import httpx

HIGGSFIELD_API_BASE = os.environ.get(
    "HIGGSFIELD_API_BASE", "https://platform.higgsfield.ai"
)

# Default text-to-video model. Env-overridable because Higgsfield's t2v
# roster is plan-dependent and not first-party-documented; seedance lite
# supports integer durations 2–12s and both 16:9 / 9:16 — exactly the
# product's 5–10s landscape+portrait envelope — at the volume-friendly tier.
DEFAULT_T2V_MODEL = os.environ.get(
    "HIGGSFIELD_T2V_MODEL", "bytedance/seedance/v1/lite/text-to-video"
)

_STATUS_PATH = "/requests/{request_id}/status"

# Terminal states per docs + official SDK enums. An UNRECOGNIZED status is
# deliberately non-terminal: keep polling until the timeout.
_SUCCESS_STATES = {"completed"}
_FAILURE_STATES = {"failed", "nsfw", "canceled", "cancelled"}

ASPECT_RATIOS = ("16:9", "9:16")

_DEFAULT_POLL_INTERVAL = 5.0   # seconds between status polls (SDK default is 2)
_DEFAULT_TIMEOUT = 600.0       # max seconds to wait for a single clip
_MAX_TRANSIENT_POLL_FAILURES = 3


class HiggsfieldError(RuntimeError):
    """A Higgsfield API call failed (HTTP error, generation failure, timeout)."""


class HiggsfieldUnavailable(HiggsfieldError):
    """Higgsfield is not configured (key/secret pair missing).

    Distinct subclass so the agent can catch "not configured" specifically
    and degrade gracefully — distinct from a real generation failure.
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
    """True when the full credential PAIR is present."""
    return bool(
        os.environ.get("HIGGSFIELD_API_KEY")
        and os.environ.get("HIGGSFIELD_API_SECRET")
    )


def _credentials() -> tuple[str, str]:
    key = os.environ.get("HIGGSFIELD_API_KEY")
    secret = os.environ.get("HIGGSFIELD_API_SECRET")
    if not key or not secret:
        missing = " and ".join(
            name for name, val in (
                ("HIGGSFIELD_API_KEY", key), ("HIGGSFIELD_API_SECRET", secret),
            ) if not val
        )
        raise HiggsfieldUnavailable(
            f"{missing} not set — video generation is not configured. "
            f"Higgsfield issues a key+secret pair (cloud.higgsfield.ai/api-keys); "
            f"add both to the environment to enable b-roll rendering."
        )
    return key, secret


def _headers() -> dict[str, str]:
    key, secret = _credentials()
    return {
        "Authorization": f"Key {key}:{secret}",
        "Content-Type": "application/json",
    }


def _error_for_response(status_code: int, text: str, *, what: str) -> HiggsfieldError:
    """Map an HTTP error to an actionable message. 403 gets special
    treatment: it means the API credit pool (separate from the web-UI
    subscription) is empty — ops can fix that without touching code."""
    snippet = (text or "")[:300]
    if status_code == 401:
        return HiggsfieldError(
            f"Higgsfield {what} failed: 401 — credentials rejected. Check the "
            f"HIGGSFIELD_API_KEY / HIGGSFIELD_API_SECRET pair."
        )
    if status_code == 403:
        return HiggsfieldError(
            f"Higgsfield {what} failed: 403 — API credits exhausted (the API "
            f"pool is separate from the web subscription; top up at "
            f"cloud.higgsfield.ai/credits)."
        )
    return HiggsfieldError(f"Higgsfield {what} failed: {status_code} {snippet}")


def classify_status(status: str) -> str:
    """'success' | 'failure' | 'pending'. Unknown statuses are pending —
    the vocabulary has grown before (canceled arrived via SDK enums)."""
    s = (status or "").lower()
    if s in _SUCCESS_STATES:
        return "success"
    if s in _FAILURE_STATES:
        return "failure"
    return "pending"


def extract_result_url(payload: dict) -> str | None:
    """Video models: payload['video']['url']; image models:
    payload['images'][0]['url']. Defensive on both per the docs' split."""
    video = payload.get("video")
    if isinstance(video, dict) and video.get("url"):
        return video["url"]
    images = payload.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict) and first.get("url"):
            return first["url"]
    return None


async def submit_generation(
    prompt: str,
    *,
    aspect_ratio: str = "16:9",
    duration_seconds: int = 6,
    model: str | None = None,
) -> str:
    """Submit a generation; return the Higgsfield request_id.

    Raises HiggsfieldUnavailable if the credential pair is missing,
    HiggsfieldError on HTTP failure.
    """
    if aspect_ratio not in ASPECT_RATIOS:
        raise HiggsfieldError(
            f"Unsupported aspect_ratio {aspect_ratio!r}; use one of {ASPECT_RATIOS}"
        )
    model = (model or DEFAULT_T2V_MODEL).strip("/")
    body = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": int(duration_seconds),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{HIGGSFIELD_API_BASE}/{model}",
            json=body,
            headers=_headers(),
        )
    if resp.status_code >= 400:
        raise _error_for_response(resp.status_code, resp.text, what="submit")
    payload = resp.json() or {}
    request_id = payload.get("request_id") or payload.get("id")
    if not request_id:
        raise HiggsfieldError(f"Higgsfield submit response had no request_id: {payload!r}")
    return str(request_id)


async def poll_generation(
    job_id: str,
    *,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str:
    """Poll a request until terminal; return the rendered clip URL.

    Transient poll failures (network blips, 5xx) are tolerated up to
    _MAX_TRANSIENT_POLL_FAILURES consecutive times. Raises HiggsfieldError
    on failed/nsfw/canceled or when `timeout` elapses.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    transient = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                resp = await client.get(
                    f"{HIGGSFIELD_API_BASE}{_STATUS_PATH.format(request_id=job_id)}",
                    headers=_headers(),
                )
            except httpx.HTTPError as e:
                transient += 1
                if transient > _MAX_TRANSIENT_POLL_FAILURES:
                    raise HiggsfieldError(f"Higgsfield status polling failed: {e!r}") from e
                await asyncio.sleep(poll_interval)
                continue
            if resp.status_code >= 500 or resp.status_code in (408, 429):
                transient += 1
                if transient > _MAX_TRANSIENT_POLL_FAILURES:
                    raise _error_for_response(resp.status_code, resp.text, what="status check")
                await asyncio.sleep(poll_interval)
                continue
            if resp.status_code >= 400:
                raise _error_for_response(resp.status_code, resp.text, what="status check")

            transient = 0
            payload = resp.json() or {}
            status = str(payload.get("status") or "").lower()
            outcome = classify_status(status)
            if outcome == "success":
                url = extract_result_url(payload)
                if not url:
                    raise HiggsfieldError(
                        f"Higgsfield request {job_id} completed without a media URL: {payload!r}"
                    )
                return url
            if outcome == "failure":
                if status == "nsfw":
                    # Moderation terminal state (auto-refunded). Retrying the
                    # same prompt is pointless — the agent should reword.
                    raise HiggsfieldError(
                        f"Higgsfield request {job_id} was flagged by content "
                        f"moderation (nsfw) — the prompt needs rewording, not a retry."
                    )
                err = payload.get("error") or status
                raise HiggsfieldError(f"Higgsfield request {job_id} failed: {err}")
            if asyncio.get_event_loop().time() >= deadline:
                raise HiggsfieldError(
                    f"Higgsfield request {job_id} did not finish within {timeout:.0f}s"
                )
            await asyncio.sleep(poll_interval)


async def download_clip(url: str) -> bytes:
    """Fetch the rendered clip bytes. Result URLs are only guaranteed for
    ~7 days — callers archive the bytes immediately (Dropbox deposit)."""
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

    This is the agent-facing entry point — its signature and GeneratedClip
    are the stable contract; everything above tracks Higgsfield's API.

    Raises HiggsfieldUnavailable when the key/secret pair isn't configured
    (the agent reports "not configured yet"), or HiggsfieldError on a real
    generation failure / moderation flag / timeout.
    """
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
