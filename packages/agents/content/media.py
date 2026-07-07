"""
Content Agent media helpers — audio acquisition + storage.

The extract_audio pipeline stage runs through this module:

  acquire_audio()      — get the podcast source audio for a video.
                         Riverside-preferred (studio quality), YouTube
                         fallback (yt-dlp bestaudio, no re-encode so no
                         ffmpeg requirement). Riverside being unconfigured
                         or unmatched is NORMAL, not an error — the fallback
                         chain only raises AudioExtractionUnavailable when
                         no source at all can produce audio.
  store_audio_asset()  — archive the audio into the org-assets bucket via
                         the shared storage_export helper and return the
                         asset descriptor the pipeline ledger records.

Audio bytes deliberately never touch LangGraph state: the checkpointer
serializes state to Postgres at every node boundary, and a 50-minute
recording is tens of MB. Bytes live only inside the extract_audio node's
frame; what crosses node boundaries is the (small) asset descriptor and the
transcript segments.

yt-dlp is a lazy optional import (same pattern as faster-whisper in
core/transcription.py): the test suite and any deploy that doesn't use the
Content Agent never need it installed, and a missing package surfaces as an
actionable message instead of an ImportError stack trace.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("content.media")


class AudioExtractionUnavailable(RuntimeError):
    """No configured source could produce audio for this video. Carries an
    actionable message (which sources were tried and why each was skipped)."""


def max_audio_bytes() -> int:
    """Byte budget for any single audio download (both Riverside and
    yt-dlp paths). Env-tunable because 'how long is the live stream' is a
    per-tenant fact; read at call time so tests can vary it."""
    try:
        mb = int(os.environ.get("CONTENT_MAX_AUDIO_MB", "512"))
    except ValueError:
        mb = 512
    return max(1, mb) * 1024 * 1024


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


async def download_youtube_audio(video_id: str) -> tuple[bytes, str]:
    """Download the upload's best audio track via yt-dlp.

    `bestaudio[ext=m4a]/bestaudio` grabs the AAC track YouTube already
    serves — no postprocessing, so ffmpeg isn't required and the bytes are
    podcast-ready m4a. Blocking work runs in a thread (yt-dlp is synchronous).

    Raises AudioExtractionUnavailable when yt-dlp isn't installed;
    RuntimeError on download failure (caller records the stage as failed).
    """
    try:
        import yt_dlp  # type: ignore
    except ImportError as e:
        raise AudioExtractionUnavailable(
            "YouTube audio extraction needs `yt-dlp`. "
            "Install it (`pip install yt-dlp`) or configure RIVERSIDE_API_KEY "
            "to source audio from Riverside instead."
        ) from e

    byte_cap = max_audio_bytes()

    def _run() -> tuple[bytes, str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            opts = {
                "format": "bestaudio[ext=m4a]/bestaudio",
                "outtmpl": os.path.join(tmpdir, "audio.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                # Same budget as the Riverside path — a marathon archive
                # must not buffer unbounded into the API process.
                "max_filesize": byte_cap,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([_watch_url(video_id)])
            files = sorted(Path(tmpdir).glob("audio.*"))
            if not files:
                raise RuntimeError(f"yt-dlp produced no audio file for {video_id}")
            path = files[0]
            ext = path.suffix.lstrip(".").lower()
            content_type = {
                "m4a": "audio/mp4",
                "mp3": "audio/mpeg",
                "opus": "audio/ogg",
                "webm": "audio/webm",
                "ogg": "audio/ogg",
            }.get(ext, "application/octet-stream")
            return path.read_bytes(), content_type

    return await asyncio.to_thread(_run)


async def acquire_audio(
    video_id: str,
    *,
    video_title: str | None = None,
    published_at: str | None = None,
) -> dict:
    """Get podcast source audio for a video, preferring Riverside.

    Returns {"bytes": ..., "content_type": ..., "source": "riverside"|"youtube"}.

    Fallback chain (per the product decision: Riverside-preferred, YouTube
    fallback):
      1. Riverside configured AND a recording matches the upload → studio audio.
      2. Otherwise → yt-dlp extraction from the upload itself.
    Riverside errors are logged and demoted to the fallback — a flaky
    Riverside call must not sink the pipeline when the YouTube path works.
    """
    from packages.integrations import riverside

    notes: list[str] = []

    if riverside.is_configured():
        try:
            recording = await riverside.find_recording_for_video(video_title, published_at)
            if recording is not None:
                audio_bytes, content_type = await riverside.download_audio(
                    recording, max_bytes=max_audio_bytes()
                )
                if audio_bytes:
                    return {
                        "bytes": audio_bytes,
                        "content_type": content_type,
                        "source": "riverside",
                    }
                notes.append("riverside: matched recording had empty audio")
            else:
                notes.append("riverside: no recording matched this upload")
        except riverside.RiversideUnavailable as e:
            notes.append(f"riverside: {e}")
        except Exception as e:
            log.warning("Riverside audio failed for %s — falling back to YouTube: %r", video_id, e)
            notes.append(f"riverside error: {e}")
    else:
        notes.append("riverside: not configured")

    try:
        audio_bytes, content_type = await download_youtube_audio(video_id)
    except AudioExtractionUnavailable as e:
        raise AudioExtractionUnavailable(
            "; ".join(notes + [f"youtube: {e}"])
        ) from e
    return {"bytes": audio_bytes, "content_type": content_type, "source": "youtube"}


_EXT_FOR_TYPE = {
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
    "audio/wav": "wav",
}


async def store_audio_asset(
    org_id: str,
    video_id: str,
    *,
    audio_bytes: bytes,
    content_type: str,
    source: str,
    video_title: str | None = None,
) -> dict:
    """Archive the audio in the org-assets bucket and return the asset
    descriptor the ledger records:

        {"kind": "audio", "storage_path": ..., "content_type": ...,
         "size_bytes": ..., "source": ..., "video_id": ...}

    storage_path is None in dev mode / on upload failure (export_to_storage
    is best-effort) — the descriptor still records what was produced so the
    pipeline's honesty doesn't depend on the bucket.
    """
    from packages.agents.core.storage_export import export_to_storage

    ext = _EXT_FOR_TYPE.get((content_type or "").lower(), "m4a")
    filename = f"{video_id}-podcast-audio.{ext}"
    storage_path = await export_to_storage(
        org_id=org_id,
        agent_slug="content",
        kind="audio",
        filename=filename,
        content=audio_bytes,
        mime_type=content_type or "audio/mp4",
        source_id=video_id,
        tags=["content-pipeline", "podcast-audio", source],
        notes=video_title,
    )
    return {
        "kind": "audio",
        "storage_path": storage_path,
        "content_type": content_type,
        "size_bytes": len(audio_bytes),
        "source": source,
        "video_id": video_id,
    }
