"""FFmpeg subprocess wrappers for video cutting, cropping, and caption burn-in."""

import subprocess
import logging

logger = logging.getLogger(__name__)


def cut_clip(input_path: str, output_path: str, start: float, end: float) -> str:
    """Cut a segment from a video file.

    Uses input seeking (-ss before -i) for speed, with re-encoding
    to ensure accurate cuts at non-keyframe boundaries.
    """
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        output_path,
    ]
    logger.info(f"Cutting clip: {start:.1f}s - {end:.1f}s")
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def crop_to_vertical(input_path: str, output_path: str) -> str:
    """Center-crop a 16:9 video to 9:16 (1080x1920).

    Takes the center vertical slice of the frame.
    """
    # crop=ih*9/16:ih crops width to 9:16 ratio, centered
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", "crop=ih*9/16:ih,scale=1080:1920",
        "-c:v", "libx264",
        "-c:a", "copy",
        "-preset", "fast",
        output_path,
    ]
    logger.info("Cropping to 9:16 vertical")
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def embed_captions(input_path: str, srt_path: str, output_path: str) -> str:
    """Embed SRT subtitles as a soft subtitle track.

    Embeds as mov_text in mp4 — players show captions when enabled.
    No libass dependency required.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-i", srt_path,
        "-c:v", "copy",
        "-c:a", "copy",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=eng",
        output_path,
    ]
    logger.info("Embedding captions")
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path
