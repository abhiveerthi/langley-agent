"""
Speech-to-text abstraction for voice notes.

A user can drop a voice note into Slack (or upload an audio clip in the app);
the Image Reader / Voice agent transcribes it to text and then handles the
text as a normal message. This module is the provider seam between "raw audio
bytes" and "a string the agent can route".

Design — one async entry point, env-selected backend:

    text = await transcribe_audio(audio_bytes, content_type="audio/ogg")

Provider is chosen by `TRANSCRIPTION_PROVIDER`:

  - "local"  (DEFAULT, free) — local `faster-whisper`. CPU-only by default,
             no API key, no per-minute cost. The model is downloaded on first
             use (so the dependency is OPTIONAL and lazily imported — the test
             suite never triggers a download). Tune with:
               FASTER_WHISPER_MODEL   (default "base")    — tiny|base|small|…
               FASTER_WHISPER_DEVICE  (default "cpu")     — cpu|cuda
               FASTER_WHISPER_COMPUTE (default "int8")    — int8|float16|…
             Install with: pip install faster-whisper

  - "openai" (hosted, paid) — OpenAI's `/v1/audio/transcriptions` (whisper-1).
             Env-swappable so a tenant who'd rather pay for latency/quality
             than run a model locally can flip one variable. Needs:
               OPENAI_API_KEY
               OPENAI_TRANSCRIBE_MODEL (default "whisper-1")

`transcribe_audio` raises `TranscriptionUnavailable` with a clear, actionable
message when the selected backend isn't installed/configured — it never
silently returns an empty string, because a blank transcript downstream looks
like "the user said nothing" rather than "we couldn't hear them".
"""
from __future__ import annotations

import functools
import os
import tempfile


@functools.lru_cache(maxsize=2)
def _cached_whisper_model(model_name: str, device: str, compute_type: str):
    """Process-wide faster-whisper model cache. Construction loads a
    multi-hundred-MB checkpoint (and downloads it on first ever use) —
    rebuilding per voice note put 1-2s+ on every transcription."""
    from faster_whisper import WhisperModel  # type: ignore

    return WhisperModel(model_name, device=device, compute_type=compute_type)


# Default backend is the free/local one. Override with TRANSCRIPTION_PROVIDER.
DEFAULT_PROVIDER = "local"


class TranscriptionUnavailable(RuntimeError):
    """Raised when the selected transcription backend can't run.

    Distinct from a transcription that ran but produced no text — this means
    the dependency is missing or the API key isn't configured. Callers surface
    it to the user as "voice transcription isn't set up" rather than treating
    it as an empty message."""


def _provider() -> str:
    return (os.environ.get("TRANSCRIPTION_PROVIDER") or DEFAULT_PROVIDER).strip().lower()


async def transcribe_audio(
    audio_bytes: bytes,
    *,
    content_type: str | None = None,
) -> str:
    """Transcribe `audio_bytes` to text using the env-selected backend.

    `content_type` (e.g. "audio/ogg", "audio/m4a") is advisory — it's used to
    pick a sensible temp-file suffix for backends that read from a path. The
    decoders sniff the real format regardless.

    Raises TranscriptionUnavailable if no backend is installed/configured.
    Returns the transcript string (stripped). May be empty only if the audio
    genuinely contained no speech.
    """
    if not audio_bytes:
        raise TranscriptionUnavailable("No audio bytes supplied to transcribe.")

    provider = _provider()
    if provider == "local":
        return await _transcribe_local(audio_bytes, content_type)
    if provider == "openai":
        return await _transcribe_openai(audio_bytes, content_type)
    raise TranscriptionUnavailable(
        f"Unknown TRANSCRIPTION_PROVIDER={provider!r}. "
        f"Use 'local' (free, faster-whisper) or 'openai' (hosted)."
    )


def _suffix_for(content_type: str | None) -> str:
    """Map a content type onto a temp-file suffix. Falls back to .ogg, which
    is what Slack voice notes ship as."""
    mapping = {
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/webm": ".webm",
    }
    return mapping.get((content_type or "").lower(), ".ogg")


async def transcribe_audio_segments(
    audio_bytes: bytes,
    *,
    content_type: str | None = None,
) -> list[dict]:
    """Like `transcribe_audio`, but returns TIMESTAMPED segments:

        [{"start": 0.0, "end": 4.2, "text": "Welcome back..."}, ...]

    Built for the Content Agent's podcast pipeline — chapter markers need to
    know WHEN a topic starts, which the plain-text seam throws away. Same
    provider selection and same TranscriptionUnavailable contract as
    `transcribe_audio`; both backends natively produce segment timings
    (faster-whisper segments / OpenAI verbose_json), so this costs nothing
    extra over the plain call.
    """
    if not audio_bytes:
        raise TranscriptionUnavailable("No audio bytes supplied to transcribe.")

    provider = _provider()
    if provider == "local":
        return await _transcribe_local_segments(audio_bytes, content_type)
    if provider == "openai":
        return await _transcribe_openai_segments(audio_bytes, content_type)
    raise TranscriptionUnavailable(
        f"Unknown TRANSCRIPTION_PROVIDER={provider!r}. "
        f"Use 'local' (free, faster-whisper) or 'openai' (hosted)."
    )


# ── Backend: local faster-whisper (free default) ──────────────────────────
async def _transcribe_local(audio_bytes: bytes, content_type: str | None) -> str:
    """Transcribe with a locally-run faster-whisper model.

    Lazy import: `faster_whisper` is an OPTIONAL dependency. Importing it
    triggers a (possibly large) model download on first transcription, so we
    only touch it when a transcription is actually requested — the test suite
    never reaches this line. A missing package surfaces as a clear install
    hint, not an ImportError stack trace.
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise TranscriptionUnavailable(
            "Local transcription needs `faster-whisper`. "
            "Install it (`pip install faster-whisper`) or set "
            "TRANSCRIPTION_PROVIDER=openai with OPENAI_API_KEY."
        ) from e

    model_name = os.environ.get("FASTER_WHISPER_MODEL", "base")
    device = os.environ.get("FASTER_WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("FASTER_WHISPER_COMPUTE", "int8")

    suffix = _suffix_for(content_type)
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        # Transcription is CPU/IO-bound and blocking. Offload to a thread so
        # we don't stall the event loop; the model itself is cached — a cold
        # WhisperModel build costs ~1-2s (plus a ~145MB download on the very
        # first call), all of it user-visible voice-note latency.
        import asyncio

        def _run() -> str:
            model = _cached_whisper_model(model_name, device, compute_type)
            segments, _info = model.transcribe(tmp.name)
            return " ".join(seg.text.strip() for seg in segments).strip()

        return await asyncio.to_thread(_run)


async def _transcribe_local_segments(
    audio_bytes: bytes, content_type: str | None
) -> list[dict]:
    """Segment-level variant of `_transcribe_local` — same model, same lazy
    import, but keeps the per-segment start/end timings."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise TranscriptionUnavailable(
            "Local transcription needs `faster-whisper`. "
            "Install it (`pip install faster-whisper`) or set "
            "TRANSCRIPTION_PROVIDER=openai with OPENAI_API_KEY."
        ) from e

    model_name = os.environ.get("FASTER_WHISPER_MODEL", "base")
    device = os.environ.get("FASTER_WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("FASTER_WHISPER_COMPUTE", "int8")

    suffix = _suffix_for(content_type)
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        import asyncio

        def _run() -> list[dict]:
            model = _cached_whisper_model(model_name, device, compute_type)
            segments, _info = model.transcribe(tmp.name)
            return [
                {"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()}
                for seg in segments
                if seg.text.strip()
            ]

        return await asyncio.to_thread(_run)


async def _transcribe_openai_segments(
    audio_bytes: bytes, content_type: str | None
) -> list[dict]:
    """Segment-level variant of `_transcribe_openai` via verbose_json."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionUnavailable(
            "TRANSCRIPTION_PROVIDER=openai needs OPENAI_API_KEY. "
            "Set it or switch to the free local backend (TRANSCRIPTION_PROVIDER=local)."
        )

    import httpx

    model = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
    suffix = _suffix_for(content_type)
    files = {
        "file": (f"audio{suffix}", audio_bytes, content_type or "application/octet-stream"),
        "model": (None, model),
        "response_format": (None, "verbose_json"),
    }
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
        )
        resp.raise_for_status()
        payload = resp.json()
    return [
        {
            "start": float(seg.get("start") or 0.0),
            "end": float(seg.get("end") or 0.0),
            "text": (seg.get("text") or "").strip(),
        }
        for seg in (payload.get("segments") or [])
        if (seg.get("text") or "").strip()
    ]


# ── Backend: hosted OpenAI Whisper (env-swappable) ─────────────────────────
async def _transcribe_openai(audio_bytes: bytes, content_type: str | None) -> str:
    """Transcribe via OpenAI's hosted audio-transcriptions endpoint.

    Uses httpx directly (already a project dep — see core/clients.py) rather
    than pulling in the OpenAI SDK, so this backend needs only an API key.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionUnavailable(
            "TRANSCRIPTION_PROVIDER=openai needs OPENAI_API_KEY. "
            "Set it or switch to the free local backend (TRANSCRIPTION_PROVIDER=local)."
        )

    import httpx

    model = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
    suffix = _suffix_for(content_type)
    files = {
        "file": (f"audio{suffix}", audio_bytes, content_type or "application/octet-stream"),
        "model": (None, model),
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
        )
        resp.raise_for_status()
        return (resp.json().get("text") or "").strip()
