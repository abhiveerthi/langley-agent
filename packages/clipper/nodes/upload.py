"""Node 5: Copy rendered clips to local output directory."""

import logging
import shutil
from pathlib import Path

from packages.clipper.state import ClipperState

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "output" / "clips"


def upload(state: ClipperState) -> dict:
    """Copy rendered clips to the local output directory."""
    output_paths = state["output_paths"]
    video_id = state["metadata"].get("id", "unknown")

    dest_dir = OUTPUT_DIR / video_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    storage_urls: list[str] = []

    for local_path in output_paths:
        filename = Path(local_path).name
        dest = dest_dir / filename
        shutil.copy2(local_path, dest)
        storage_urls.append(str(dest))
        logger.info(f"Saved: {dest}")

    return {"storage_urls": storage_urls}
