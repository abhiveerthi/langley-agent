"""
Podcast episode drafting — models + pure helpers.

The draft_podcast pipeline stage turns a timestamped transcript into a
publish-ready episode draft under the org's podcast brand (config key
`podcast_brand`, e.g. "Positively American with Braden Langley"):

  PodcastEpisode      — the structured contract (title, description,
                        chapters with HH:MM:SS starts). Doubles as the LLM's
                        structured-output schema and the FE card shape.
  build_timed_transcript — collapse whisper segments into "[HH:MM:SS] text"
                        lines, downsampled to a char budget so a 55-minute
                        stream fits the prompt without losing the time grid
                        chapters are anchored to.

The LLM call itself lives in the agent node (agent.py) — this module stays
pure so every transform is unit-testable without a model in the loop.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# Keep the prompt's transcript block bounded. ~60k chars ≈ 15k tokens —
# comfortable alongside the system prompt, and a 45–55 min episode's
# transcript (~9k words) usually fits WITHOUT downsampling; the cap is the
# safety rail for marathon streams, not the normal path.
TRANSCRIPT_CHAR_BUDGET = 60_000


class ChapterMarker(BaseModel):
    start: str = Field(
        description="Chapter start time as HH:MM:SS, taken from the "
        "[HH:MM:SS] markers in the transcript — never invent a time that "
        "isn't near a marker you saw."
    )
    title: str = Field(description="Short, listener-facing chapter title.")


class PodcastEpisode(BaseModel):
    title: str = Field(
        description="Episode title. Punchy, specific to what was actually "
        "discussed — not a restatement of the show name."
    )
    description: str = Field(
        description="Show notes: 2–4 paragraphs a podcast app displays. "
        "Hook first, then what's covered. Written in the creator's voice."
    )
    summary: str = Field(
        description="One-sentence episode summary (feed <itunes:summary>)."
    )
    chapters: list[ChapterMarker] = Field(
        default_factory=list,
        description="6–12 chapter markers spanning the whole episode, "
        "in chronological order, starting at 00:00:00.",
    )


def seconds_to_hms(seconds: float | int) -> str:
    total = max(0, int(seconds or 0))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def hms_to_seconds(hms: str) -> int:
    """Parse HH:MM:SS (or MM:SS) back to seconds; 0 on garbage — a chapter
    with a mangled timestamp degrades to the episode start rather than
    crashing feed generation."""
    try:
        parts = [int(p) for p in str(hms).strip().split(":")]
    except (ValueError, AttributeError):
        return 0
    if not parts or len(parts) > 3:
        return 0
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return max(0, h * 3600 + m * 60 + s)


def build_timed_transcript(
    segments: list[dict],
    *,
    char_budget: int = TRANSCRIPT_CHAR_BUDGET,
) -> str:
    """Render whisper segments as "[HH:MM:SS] text" lines within a budget.

    When the full render exceeds the budget, segments are evenly SAMPLED
    (never truncated from the tail) — chapters need anchors across the WHOLE
    episode, and naive truncation would blind the model to the second half.
    """
    lines = [
        f"[{seconds_to_hms(seg.get('start', 0))}] {(seg.get('text') or '').strip()}"
        for seg in (segments or [])
        if (seg.get("text") or "").strip()
    ]
    if not lines:
        return ""
    full = "\n".join(lines)
    if len(full) <= char_budget:
        return full

    # Even sampling: keep every k-th line so coverage stays uniform. Step
    # rounds UP — flooring would give step=1 whenever the transcript is
    # between 1x and 2x the budget, silently reverting to tail truncation
    # (exactly the failure mode sampling exists to avoid).
    import math

    avg_len = max(1, len(full) // len(lines))
    keep = max(2, char_budget // avg_len)
    step = max(1, math.ceil(len(lines) / keep))
    sampled = lines[::step]
    return "\n".join(sampled)[:char_budget]


def episode_asset(
    episode: PodcastEpisode | dict,
    *,
    audio_asset: dict | None,
    podcast_brand: str,
    video_id: str,
) -> dict:
    """Build the ledger asset descriptor for a drafted episode. Accepts the
    model or its dump so callers off the LLM path (tests, retries) can use
    plain dicts."""
    data = episode.model_dump() if isinstance(episode, PodcastEpisode) else dict(episode)
    return {
        "kind": "podcast_episode",
        "title": data.get("title") or "",
        "summary": data.get("summary") or "",
        "description": data.get("description") or "",
        "chapters": data.get("chapters") or [],
        "brand": podcast_brand,
        "video_id": video_id,
        "audio_storage_path": (audio_asset or {}).get("storage_path"),
        "audio_content_type": (audio_asset or {}).get("content_type"),
        "audio_size_bytes": (audio_asset or {}).get("size_bytes"),
    }
