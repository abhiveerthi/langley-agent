"""
Self-hosted podcast RSS — feed generation + public-bucket hosting.

Spotify and Apple Podcasts have no "upload an episode" API; they subscribe
to an RSS feed and ingest whatever it lists. So publishing a podcast
episode means: copy the approved audio into the public bucket, rebuild the
show's feed.xml from every published episode, upload it, done. Submitting
the feed URL to Spotify/Apple is a one-time manual step when the show
launches; after that, new items in the feed appear on both platforms
automatically.

`build_feed` is pure (unit-tested XML assembly, fully escaped); the
storage I/O lives in small helpers the publish runner calls.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

PODCAST_BUCKET = "podcast-public"

# XML 1.0 forbids most control chars entirely — escaping can't represent
# them. LLM/whisper text shouldn't contain any, but one stray byte would
# invalidate the whole feed for every subscriber.
_XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9_-]")


def _esc(value: Any, entities: dict | None = None) -> str:
    """Escape for XML content/attributes, stripping XML-invalid control
    characters first."""
    return _xml_escape(_XML_INVALID.sub("", str(value or "")), entities or {})


def public_url(supabase_url: str, path: str) -> str:
    """Public object URL for a path inside the podcast bucket."""
    return f"{supabase_url.rstrip('/')}/storage/v1/object/public/{PODCAST_BUCKET}/{path}"


def feed_path(org_id: str) -> str:
    return f"{org_id}/feed.xml"


def episode_audio_path(org_id: str, video_id: str, ext: str = "m4a") -> str:
    # video_id comes from the YouTube API ([A-Za-z0-9_-]{11} in practice)
    # but it's third-party data landing in a PUBLIC bucket key — sanitize
    # so it can never traverse or collide outside its episodes/ folder.
    safe = _SAFE_SEGMENT.sub("_", str(video_id or ""))[:32] or "episode"
    return f"{org_id}/episodes/{safe}.{ext}"


def _rfc2822(iso_ts: str | None) -> str:
    if iso_ts:
        try:
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return format_datetime(dt)
        except ValueError:
            pass
    return format_datetime(datetime.now(timezone.utc))


def build_feed(
    *,
    show_title: str,
    show_description: str,
    show_link: str,
    episodes: list[dict],
) -> str:
    """Render an RSS 2.0 + iTunes feed. Each episode dict:

        {"title", "description", "summary", "audio_url", "audio_type",
         "audio_size_bytes", "guid", "published_at" (iso), "chapters"}

    Newest episode first (podcast apps expect reverse-chronological).
    Everything user-controlled is XML-escaped — episode titles/notes come
    from an LLM over spoken audio and must never break the feed.
    """
    items: list[str] = []
    for ep in episodes:
        title = _esc(ep.get("title") or "Untitled episode")
        description = _esc(ep.get("description") or "")
        summary = _esc(ep.get("summary") or "")
        guid = _esc(ep.get("guid") or ep.get("audio_url") or title)
        audio_url = _esc(ep.get("audio_url") or "", {'"': "&quot;"})
        audio_type = _esc(ep.get("audio_type") or "audio/mp4", {'"': "&quot;"})
        size = int(ep.get("audio_size_bytes") or 0)
        pub = _rfc2822(ep.get("published_at"))

        # Chapter rows are built UNESCAPED and escaped exactly once below —
        # escaping the parts and then the whole double-encodes ('&' → '&amp;amp;').
        chapter_lines = ""
        chapters = ep.get("chapters") or []
        if chapters:
            rows = "\n".join(
                f"{c.get('start') or '00:00:00'} — {c.get('title') or ''}"
                for c in chapters
            )
            chapter_lines = f"\n\nChapters:\n{rows}"

        items.append(f"""    <item>
      <title>{title}</title>
      <description>{description}{_esc(chapter_lines)}</description>
      <itunes:summary>{summary}</itunes:summary>
      <enclosure url="{audio_url}" length="{size}" type="{audio_type}"/>
      <guid isPermaLink="false">{guid}</guid>
      <pubDate>{pub}</pubDate>
    </item>""")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{_esc(show_title)}</title>
    <link>{_esc(show_link)}</link>
    <language>en-us</language>
    <description>{_esc(show_description)}</description>
    <itunes:explicit>false</itunes:explicit>
{chr(10).join(items)}
  </channel>
</rss>
"""


# ── Storage I/O (service-role client, thread-offloaded sync calls) ─────────

async def copy_audio_to_public(
    supabase: Any,
    org_id: str,
    video_id: str,
    *,
    source_storage_path: str,
    content_type: str,
) -> str:
    """Copy an approved episode's audio from private org-assets into the
    public podcast bucket. Returns the public path. Raises on failure —
    an episode without public audio must not enter the feed."""
    ext = "m4a" if "mp4" in (content_type or "") else "mp3"
    dest = episode_audio_path(org_id, video_id, ext)

    def _copy() -> None:
        data = supabase.storage.from_("org-assets").download(source_storage_path)
        supabase.storage.from_(PODCAST_BUCKET).upload(
            dest, data,
            {"content-type": content_type or "audio/mp4", "upsert": "true"},
        )

    await asyncio.to_thread(_copy)
    return dest


async def upload_feed(supabase: Any, org_id: str, xml: str) -> str:
    """Write/overwrite the org's feed.xml. Returns the bucket path."""
    dest = feed_path(org_id)

    def _put() -> None:
        supabase.storage.from_(PODCAST_BUCKET).upload(
            dest, xml.encode("utf-8"),
            {"content-type": "application/rss+xml", "upsert": "true"},
        )

    await asyncio.to_thread(_put)
    return dest


def collect_published_episodes(supabase: Any, org_id: str, supabase_url: str) -> list[dict]:
    """Every published, reviewer-approved podcast episode for the org, as
    feed-ready dicts (newest first). Reads the pipeline ledger — the review
    gate upstream is what guarantees nothing unapproved lands here."""
    resp = (
        supabase.table("content_pipelines")
        .select("video_id, assets, published_at, detected_at")
        .eq("org_id", org_id)
        .eq("status", "published")
        .order("detected_at", desc=True)
        .limit(200)
        .execute()
    )
    episodes: list[dict] = []
    for row in resp.data or []:
        for asset in row.get("assets") or []:
            if asset.get("kind") != "podcast_episode":
                continue
            if asset.get("approved") is not True:
                continue
            public_path = asset.get("public_audio_path")
            if not public_path:
                continue
            episodes.append({
                "title": asset.get("title"),
                "description": asset.get("description"),
                "summary": asset.get("summary"),
                "audio_url": public_url(supabase_url, public_path),
                "audio_type": asset.get("audio_content_type") or "audio/mp4",
                "audio_size_bytes": asset.get("audio_size_bytes") or 0,
                "guid": f"content-agent-{org_id}-{row.get('video_id')}",
                "published_at": row.get("published_at"),
                "chapters": asset.get("chapters") or [],
            })
    return episodes
