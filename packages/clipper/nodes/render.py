"""Node 4: Render clips — cut, crop to 9:16, burn in captions."""

import logging
import re
from pathlib import Path

from packages.clipper.state import ClipperState
from packages.clipper.utils.ffmpeg import cut_clip, crop_to_vertical, embed_captions
from packages.clipper.utils.captions import generate_srt

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:60]


def render(state: ClipperState) -> dict:
    """Render each detected clip: cut → crop → captions."""
    video_path = state["video_path"]
    transcript = state["transcript"]
    clips = state["clips"]
    video_id = state["metadata"].get("id", "video")

    work_dir = Path(video_path).parent / f"{video_id}_clips"
    work_dir.mkdir(parents=True, exist_ok=True)

    output_paths: list[str] = []

    for i, clip in enumerate(clips):
        slug = _slugify(clip["title"])
        prefix = f"{i+1:02d}_{slug}"

        logger.info(f"Rendering clip {i+1}/{len(clips)}: {clip['title']}")

        # Step 1: Cut segment from source
        cut_path = str(work_dir / f"{prefix}_cut.mp4")
        cut_clip(video_path, cut_path, clip["start"], clip["end"])

        # Step 2: Crop to vertical 9:16
        cropped_path = str(work_dir / f"{prefix}_cropped.mp4")
        crop_to_vertical(cut_path, cropped_path)

        # Step 3: Generate SRT captions
        srt_path = str(work_dir / f"{prefix}.srt")
        generate_srt(transcript, clip["start"], clip["end"], srt_path)

        # Step 4: Embed captions as subtitle track
        final_path = str(work_dir / f"{prefix}.mp4")
        embed_captions(cropped_path, srt_path, final_path)

        output_paths.append(final_path)

        # Clean up intermediate files
        Path(cut_path).unlink(missing_ok=True)
        Path(cropped_path).unlink(missing_ok=True)

        logger.info(f"Rendered: {final_path}")

    return {"output_paths": output_paths}
