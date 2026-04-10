"""Node 1: Download video and extract metadata via yt-dlp."""

import json
import subprocess
import tempfile
import logging
from pathlib import Path

from packages.clipper.state import ClipperState

logger = logging.getLogger(__name__)

WORK_DIR = Path(tempfile.gettempdir()) / "clipper"


def ingest(state: ClipperState) -> dict:
    """Download a YouTube video and extract metadata, heatmap, and chapters."""
    url = state["video_url"]
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    output_template = str(WORK_DIR / "%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--write-info-json",
        "--no-playlist",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", output_template,
        url,
    ]

    logger.info(f"Downloading: {url}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    logger.info("Download complete")

    # Find the downloaded files
    info_files = list(WORK_DIR.glob("*.info.json"))
    if not info_files:
        raise RuntimeError("yt-dlp did not produce an info JSON file")

    # Use the most recently modified info file
    info_path = max(info_files, key=lambda p: p.stat().st_mtime)

    with open(info_path) as f:
        info = json.load(f)

    video_id = info.get("id", "unknown")
    video_path = str(WORK_DIR / f"{video_id}.mp4")

    # Extract heatmap data (yt-dlp includes this natively)
    heatmap = info.get("heatmap") or []

    # Extract chapters if available
    chapters = info.get("chapters") or []

    metadata = {
        "id": video_id,
        "title": info.get("title", ""),
        "description": info.get("description", ""),
        "duration": info.get("duration", 0),
        "chapters": chapters,
        "uploader": info.get("uploader", ""),
    }

    logger.info(
        f"Ingested: '{metadata['title']}' "
        f"({metadata['duration']}s, {len(heatmap)} heatmap points, {len(chapters)} chapters)"
    )

    return {
        "video_path": video_path,
        "metadata": metadata,
        "heatmap": heatmap,
    }
