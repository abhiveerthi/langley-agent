#!/usr/bin/env python3
"""
Video Auto-Clipper — CLI

Downloads a YouTube video, transcribes it, detects viral moments,
renders vertical clips with captions, and uploads to Supabase Storage.

Usage:
    python clip.py <youtube-url>
    python clip.py https://www.youtube.com/watch?v=dQw4w9WgXcQ
"""

import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from packages.clipper.workflow import run_clipper


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="  %(name)s | %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python clip.py <youtube-url>")
        sys.exit(1)

    url = sys.argv[1]
    print()
    print("=" * 56)
    print("  MARCUS — Video Auto-Clipper")
    print("=" * 56)
    print(f"\n  URL: {url}\n")

    result = run_clipper(url)

    print("\n" + "=" * 56)
    print("  Results")
    print("=" * 56)

    clips = result.get("clips", [])
    urls = result.get("storage_urls", [])

    for i, clip in enumerate(clips):
        print(f"\n  Clip {i+1}: {clip['title']}")
        print(f"    Time:  {clip['start']:.1f}s — {clip['end']:.1f}s")
        print(f"    Score: {clip['score']:.2f}")
        if i < len(urls):
            print(f"    URL:   {urls[i]}")

    print()


if __name__ == "__main__":
    main()
