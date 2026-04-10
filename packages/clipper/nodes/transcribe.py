"""Node 2: Transcribe video audio using faster-whisper."""

import logging

from faster_whisper import WhisperModel

from packages.clipper.state import ClipperState

logger = logging.getLogger(__name__)

# Lazy-loaded model singleton
_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        logger.info("Loading Whisper model (base)...")
        _model = WhisperModel("base", compute_type="int8")
    return _model


def transcribe(state: ClipperState) -> dict:
    """Transcribe audio to word-level timestamped segments."""
    video_path = state["video_path"]
    model = _get_model()

    logger.info(f"Transcribing: {video_path}")
    segments, info = model.transcribe(video_path, word_timestamps=True)

    transcript: list[dict] = []
    for segment in segments:
        if segment.words:
            for word in segment.words:
                transcript.append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end,
                })

    logger.info(f"Transcribed {len(transcript)} words ({info.language}, {info.language_probability:.0%} confidence)")

    return {"transcript": transcript}
