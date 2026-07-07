"""
Riverside.fm client — pull clean source audio for the Content Agent.

The creator records the daily live stream in Riverside; the raw studio audio
there is higher quality than the YouTube encode. When a new upload is
detected, the Content Agent asks this client for the matching Riverside
recording and uses its audio as the podcast source, falling back to
extracting audio from the YouTube upload itself when Riverside isn't
configured or has no matching recording (see packages/agents/content/media.py).

Gating mirrors the Higgsfield pattern: `is_configured()` checks
RIVERSIDE_API_KEY; every network entry point raises `RiversideUnavailable`
when the key is absent, so callers can degrade gracefully instead of
crashing a pipeline run.

NOTE ON ENDPOINTS: Riverside's public API is young and access is
plan-gated. The paths below are isolated in module constants so that when a
real key lands and the account's API shape is confirmed, any drift is a
one-constant fix — the matching logic (`match_recording`, pure + unit
tested) and the caller contract don't change.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

BASE_URL = "https://api.riverside.fm/v1"
RECORDINGS_PATH = "/recordings"

# How far a Riverside recording's start may sit from the YouTube video's
# publish time and still count as "the same session". The 8PM live stream is
# recorded and published the same evening; a generous window absorbs upload
# delays without matching yesterday's session.
MATCH_WINDOW_HOURS = 12


class RiversideUnavailable(RuntimeError):
    """Riverside isn't configured (no RIVERSIDE_API_KEY). Callers treat this
    as "use the fallback audio source", never as a pipeline failure."""


class RiversideError(RuntimeError):
    """Riverside is configured but a call failed (HTTP error, bad payload)."""


def is_configured() -> bool:
    return bool(os.environ.get("RIVERSIDE_API_KEY"))


def _headers() -> dict[str, str]:
    key = os.environ.get("RIVERSIDE_API_KEY")
    if not key:
        raise RiversideUnavailable(
            "Riverside isn't configured — set RIVERSIDE_API_KEY to pull "
            "studio audio; the pipeline falls back to YouTube audio without it."
        )
    return {"Authorization": f"Bearer {key}"}


async def list_recent_recordings(limit: int = 20) -> list[dict]:
    """Most recent recordings, newest first. Normalized to
    {id, title, started_at, audio_url} regardless of payload shape drift."""
    headers = _headers()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{BASE_URL}{RECORDINGS_PATH}",
            params={"limit": max(1, min(int(limit), 50))},
            headers=headers,
        )
    if resp.status_code >= 400:
        raise RiversideError(
            f"Riverside recordings list failed: {resp.status_code} {resp.text[:300]}"
        )
    payload = resp.json()
    items = payload.get("recordings") or payload.get("data") or []
    return [_normalize_recording(r) for r in items if isinstance(r, dict)]


def _normalize_recording(raw: dict) -> dict:
    """Collapse plausible payload shapes onto one contract the matcher and
    downloader rely on."""
    return {
        "id": raw.get("id") or raw.get("recording_id"),
        "title": raw.get("title") or raw.get("name") or "",
        "started_at": raw.get("started_at") or raw.get("created_at"),
        "audio_url": (
            raw.get("audio_url")
            or (raw.get("media") or {}).get("audio_url")
            or raw.get("download_url")
        ),
    }


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def match_recording(
    video_title: str | None,
    published_at: str | None,
    recordings: list[dict],
) -> dict | None:
    """Pick the Riverside recording that corresponds to a YouTube upload.

    Pure (unit-tested) so the matching policy is inspectable without a live
    account. Policy, in priority order:

      1. Time proximity: recording started within MATCH_WINDOW_HOURS of the
         video's publish time. Among those, the closest wins.
      2. If the video has no usable publish time, fall back to a title
         token-overlap check (>= 50% of the video title's significant words
         appear in the recording title); best overlap wins.

    Returns None when nothing matches — the caller then uses YouTube audio.
    Recordings without a downloadable audio_url never match.
    """
    usable = [r for r in recordings if r.get("audio_url")]
    if not usable:
        return None

    pub = _parse_ts(published_at)
    if pub is not None:
        window = timedelta(hours=MATCH_WINDOW_HOURS)
        best: tuple[timedelta, dict] | None = None
        for r in usable:
            start = _parse_ts(r.get("started_at"))
            if start is None:
                continue
            gap = abs(pub - start)
            if gap <= window and (best is None or gap < best[0]):
                best = (gap, r)
        if best:
            return best[1]
        return None

    title_words = {
        w for w in (video_title or "").lower().split() if len(w) > 3
    }
    if not title_words:
        return None
    best_overlap: tuple[float, dict] | None = None
    for r in usable:
        rec_words = set((r.get("title") or "").lower().split())
        if not rec_words:
            continue
        overlap = len(title_words & rec_words) / len(title_words)
        if overlap >= 0.5 and (best_overlap is None or overlap > best_overlap[0]):
            best_overlap = (overlap, r)
    return best_overlap[1] if best_overlap else None


async def find_recording_for_video(
    video_title: str | None, published_at: str | None
) -> dict | None:
    """List recent recordings and match one to the upload. Raises
    RiversideUnavailable when unconfigured, RiversideError on API failure."""
    recordings = await list_recent_recordings()
    return match_recording(video_title, published_at, recordings)


DEFAULT_MAX_AUDIO_BYTES = 512 * 1024 * 1024  # matches CONTENT_MAX_AUDIO_MB default


def _should_send_auth(url: str) -> bool:
    """Only attach the bearer key to Riverside's own hosts. audio_url is
    normally a presigned CDN/S3 URL on a third-party host — sending the API
    key there both leaks the credential to whoever runs that host and (for
    S3) can outright 400 the request (presigned URLs reject a second auth
    mechanism)."""
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host == "riverside.fm" or host.endswith(".riverside.fm")


async def download_audio(
    recording: dict, *, max_bytes: int = DEFAULT_MAX_AUDIO_BYTES
) -> tuple[bytes, str]:
    """Download a matched recording's audio. Returns (bytes, content_type).

    Streamed with a byte budget: a marathon session's studio WAV (or a
    hostile URL) must not buffer unbounded into the API process — past
    `max_bytes` the download aborts with a clear RiversideError and the
    pipeline falls back to YouTube audio.
    """
    url = recording.get("audio_url")
    if not url:
        raise RiversideError(f"Recording {recording.get('id')!r} has no audio_url")
    headers = _headers() if _should_send_auth(url) else {}
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise RiversideError(
                    f"Riverside audio download failed: {resp.status_code} {body[:300]!r}"
                )
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise RiversideError(
                    f"Riverside audio is {int(declared) // (1024 * 1024)}MB — over the "
                    f"{max_bytes // (1024 * 1024)}MB cap (CONTENT_MAX_AUDIO_MB)"
                )
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise RiversideError(
                        f"Riverside audio exceeded the {max_bytes // (1024 * 1024)}MB "
                        f"cap mid-download (CONTENT_MAX_AUDIO_MB)"
                    )
                chunks.append(chunk)
            content_type = resp.headers.get("content-type") or "audio/mpeg"
    return b"".join(chunks), content_type.split(";")[0].strip()
