"""Node 3: Detect best clip segments using heatmap peaks + LLM analysis."""

import json
import logging

from anthropic import Anthropic

from packages.clipper.state import ClipperState
from packages.clipper.utils.heatmap import find_peaks

logger = logging.getLogger(__name__)

DETECT_PROMPT = """\
You are a short-form video editor. Given a transcript and engagement heatmap peaks \
from a YouTube video, select the 3-5 best segments to clip into vertical Shorts.

Each segment must be:
- 30-60 seconds long
- Self-contained (makes sense without context)
- Has a strong hook in the first 3 seconds
- High energy, funny, opinionated, or tells a complete story

If heatmap peaks are provided, prefer segments that overlap with them.

Respond with ONLY a JSON array. No markdown, no explanation:
[
  {"start": 120.5, "end": 165.0, "title": "short descriptive title", "score": 0.95},
  ...
]

Score from 0-1 based on viral potential. Order by score descending.\
"""


def _build_transcript_text(transcript: list[dict]) -> str:
    """Build a readable transcript with timestamps."""
    lines: list[str] = []
    current_line: list[str] = []
    line_start = 0.0

    for word in transcript:
        if not current_line:
            line_start = word["start"]
        current_line.append(word["word"])

        if len(current_line) >= 12:
            timestamp = f"[{line_start:.1f}s]"
            lines.append(f"{timestamp} {' '.join(current_line)}")
            current_line = []

    if current_line:
        timestamp = f"[{line_start:.1f}s]"
        lines.append(f"{timestamp} {' '.join(current_line)}")

    return "\n".join(lines)


def detect_clips(state: ClipperState) -> dict:
    """Identify peak moments by combining heatmap data with LLM analysis."""
    transcript = state["transcript"]
    heatmap = state["heatmap"]
    metadata = state["metadata"]

    peaks = find_peaks(heatmap) if heatmap else []
    transcript_text = _build_transcript_text(transcript)

    # Build context for the LLM
    peaks_text = ""
    if peaks:
        peaks_text = "\n\nHeatmap peaks (high viewer engagement):\n"
        for p in peaks[:10]:
            peaks_text += f"- {p['start']:.0f}s to {p['end']:.0f}s (intensity: {p['peak_value']:.2f})\n"

    user_message = (
        f"Video: {metadata.get('title', 'Unknown')}\n"
        f"Duration: {metadata.get('duration', 0):.0f}s\n"
        f"{peaks_text}\n"
        f"Transcript:\n{transcript_text}"
    )

    client = Anthropic()
    logger.info("Detecting clips with Sonnet...")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": f"{DETECT_PROMPT}\n\n{user_message}"},
        ],
    )

    raw = response.content[0].text.strip()

    # Parse JSON response (strip markdown fences if present)
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]

    clips = json.loads(raw)

    # Validate and clamp
    duration = metadata.get("duration", float("inf"))
    validated: list[dict] = []
    for clip in clips:
        start = max(0, float(clip["start"]))
        end = min(duration, float(clip["end"]))
        if end - start >= 15:
            validated.append({
                "start": start,
                "end": end,
                "title": clip["title"],
                "score": float(clip["score"]),
            })

    validated.sort(key=lambda c: c["score"], reverse=True)
    logger.info(f"Detected {len(validated)} clips")

    return {"clips": validated}
