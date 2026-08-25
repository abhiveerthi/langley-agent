"""
Higgsfield video-generation client (platform.higgsfield.ai).

Submits a text prompt, polls the request to completion, and returns the
rendered b-roll clip (URL + bytes). Used by the B-Roll Producer agent to
turn AI-written b-roll scripts into short interrupt-style clips.

VERIFIED API CONTRACT (probed LIVE against the client's account, Aug 2026)
--------------------------------------------------------------------------
  Auth:    ONE header — `Authorization: Key {api_key}:{api_secret}` (the
           literal word "Key"). Keys are issued as a PAIR at
           cloud.higgsfield.ai/api-keys; both parts are required.
           (Verified live: bogus-id status GET returns 404 with good
           creds, 401 with bad ones.)
  Models:  GET /models (auth'd) lists the account's roster. THERE IS NO
           TEXT2VIDEO MODEL — only image2video (higgsfield-ai/dop/*) and
           text2image (higgsfield-ai/soul/*, popcorn). A clip therefore
           renders as a TWO-STEP CHAIN: t2i (Soul) → i2v (DoP), both
           env-overridable below. Base credits per call come back in the
           roster (dop/lite/first-last-frame = 2.0, dop/turbo = 6.5,
           dop/standard = 9.0; soul/v2/standard and soul/cinema were 0.0).
  Submit:  POST https://platform.higgsfield.ai/{model_slug} with a FLAT
           JSON body. Required fields verified via empty-body 422 probes
           (FastAPI echoes them): soul → {"prompt"}; dop → {"prompt",
           "image_url"}. Optional-field acceptance (aspect_ratio,
           duration) is UNVERIFIED — submits are adaptive: optional keys
           are dropped and retried once when a 422 names only them.
           200 → {"status": "queued", "request_id": ..., "status_url": ...}
           404 {"detail": "model_not_found"} → slug not on this account.
  Poll:    GET /requests/{request_id}/status
           Statuses: queued | in_progress | completed | failed | nsfw |
           canceled. Anything unrecognized is treated as NON-terminal
           (poll on until timeout) — the vocabulary has grown before.
           completed → "video": {"url": ...} for video models,
           "images": [{"url": ...}] for image models (extractor tries both).
  Errors:  401 bad credentials · 403 {"detail": "not_enough_credits"} =
           API credit pool empty (SEPARATE pool from the web subscription;
           top up at cloud.higgsfield.ai) · 422 validation (Pydantic
           `detail`).

Operational notes for the daily batch:
  - Result URLs are only guaranteed ~7 days — callers must download and
    archive immediately (generate_clip(download=True) does).
  - `nsfw` is a moderation terminal state, auto-refunded — surfaced with
    its own message; retrying the SAME prompt is pointless.
  - failed/timeout are auto-refunded by Higgsfield.
  - generate_image() exposes the t2i step directly — thumbnails/memes,
    the client's other actively-used Higgsfield workflow.

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

# The two-step chain models (no text2video exists on the platform API —
# verified live against GET /models). Env-overridable because the roster
# is plan-dependent; slugs must appear in the account's /models response.
DEFAULT_T2I_MODEL = os.environ.get(
    "HIGGSFIELD_T2I_MODEL", "higgsfield-ai/soul/v2/standard"
)
DEFAULT_I2V_MODEL = os.environ.get(
    "HIGGSFIELD_I2V_MODEL", "higgsfield-ai/dop/lite/first-last-frame"
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


@dataclass
class GeneratedImage:
    """A rendered still image (Soul/Popcorn) — thumbnails, memes, and the
    intermediate frame of the clip chain."""
    job_id: str
    url: str
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
            f"Higgsfield {what} failed: 403 not_enough_credits — the API "
            f"credit pool is empty (it's SEPARATE from the web subscription; "
            f"top up at cloud.higgsfield.ai)."
        )
    if status_code == 404 and "model_not_found" in snippet:
        return HiggsfieldError(
            f"Higgsfield {what} failed: model_not_found — that model slug "
            f"isn't on this account's plan (GET /models lists the roster; "
            f"set HIGGSFIELD_T2I_MODEL / HIGGSFIELD_I2V_MODEL accordingly)."
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


async def submit_request(model: str, body: dict, *, what: str = "submit") -> str:
    """POST one generation request; return the Higgsfield request_id.

    Raises HiggsfieldUnavailable if the credential pair is missing,
    HiggsfieldError on HTTP failure (403 credits / 404 model / 422 body).
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{HIGGSFIELD_API_BASE}/{model.strip('/')}",
            json=body,
            headers=_headers(),
        )
    if resp.status_code >= 400:
        raise _error_for_response(resp.status_code, resp.text, what=what)
    payload = resp.json() or {}
    request_id = payload.get("request_id") or payload.get("id")
    if not request_id:
        raise HiggsfieldError(f"Higgsfield submit response had no request_id: {payload!r}")
    return str(request_id)


def _optional_only_422(detail_text: str, optional_keys: set[str]) -> bool:
    """True when a 422's field errors reference ONLY our optional keys —
    i.e. the model rejects extras we volunteered, not anything required."""
    import json as _json

    try:
        detail = _json.loads(detail_text).get("detail") or []
    except Exception:
        return False
    if not isinstance(detail, list) or not detail:
        return False
    for err in detail:
        loc = err.get("loc") or []
        field = str(loc[-1]) if loc else ""
        if field not in optional_keys:
            return False
    return True


async def submit_adaptive(
    model: str, required: dict, optional: dict, *, what: str = "submit"
) -> str:
    """Submit with optional fields, transparently retrying without them
    when the model's schema rejects ONLY those fields (422). Verified
    required fields per model came from empty-body 422 probes; optional
    acceptance (aspect_ratio/duration) is plan/model-dependent, so the
    client adapts instead of hardcoding a guess."""
    body = {**required, **{k: v for k, v in optional.items() if v is not None}}
    try:
        return await submit_request(model, body, what=what)
    except HiggsfieldError as e:
        if optional and "422" in str(e) and _optional_only_422(
            str(e).split("422", 1)[-1], set(optional)
        ):
            return await submit_request(model, dict(required), what=what)
        raise


async def generate_image(
    prompt: str,
    *,
    aspect_ratio: str = "16:9",
    model: str | None = None,
    download: bool = False,
    poll_interval: float = _DEFAULT_POLL_INTERVAL,
    timeout: float = 300.0,
) -> GeneratedImage:
    """Render one still image (Soul) — thumbnails, memes, or the first
    frame of the clip chain. Raises HiggsfieldUnavailable when the pair
    isn't configured, HiggsfieldError on failure/moderation/timeout."""
    if aspect_ratio not in ASPECT_RATIOS:
        raise HiggsfieldError(
            f"Unsupported aspect_ratio {aspect_ratio!r}; use one of {ASPECT_RATIOS}"
        )
    job_id = await submit_adaptive(
        model or DEFAULT_T2I_MODEL,
        {"prompt": prompt},
        {"aspect_ratio": aspect_ratio},
        what="image submit",
    )
    url = await poll_generation(job_id, poll_interval=poll_interval, timeout=timeout)
    raw = await download_clip(url) if download else None
    return GeneratedImage(job_id=job_id, url=url, prompt=prompt, bytes_=raw)


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
    """End-to-end clip render via the verified TWO-STEP CHAIN:
    text2image (Soul) → image2video (DoP), one shared time budget.

    This is the agent-facing entry point — its signature and GeneratedClip
    are the stable contract; the chain is an internal detail (the platform
    API has no text2video model, verified live against GET /models).

    Raises HiggsfieldUnavailable when the key/secret pair isn't configured
    (the agent reports "not configured yet"), or HiggsfieldError on a real
    generation failure / moderation flag / timeout at either step.
    """
    if aspect_ratio not in ASPECT_RATIOS:
        raise HiggsfieldError(
            f"Unsupported aspect_ratio {aspect_ratio!r}; use one of {ASPECT_RATIOS}"
        )
    deadline = asyncio.get_event_loop().time() + timeout

    # Step 1 — first frame. The Soul aspect_ratio drives the clip's shape
    # (DoP animates the frame it's given).
    image_job = await submit_adaptive(
        DEFAULT_T2I_MODEL,
        {"prompt": prompt},
        {"aspect_ratio": aspect_ratio},
        what="image submit",
    )
    remaining = max(30.0, deadline - asyncio.get_event_loop().time())
    image_url = await poll_generation(
        image_job, poll_interval=poll_interval, timeout=remaining
    )

    # Step 2 — animate it.
    job_id = await submit_adaptive(
        DEFAULT_I2V_MODEL,
        {"prompt": prompt, "image_url": image_url},
        {"duration": int(duration_seconds)},
        what="video submit",
    )
    remaining = max(30.0, deadline - asyncio.get_event_loop().time())
    url = await poll_generation(job_id, poll_interval=poll_interval, timeout=remaining)
    raw = await download_clip(url) if download else None
    return GeneratedClip(
        job_id=job_id,
        url=url,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        prompt=prompt,
        bytes_=raw,
    )
