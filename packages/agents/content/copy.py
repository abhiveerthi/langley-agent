"""
SEO/social copy drafting — models + pure helpers.

Per the product clarification: captions, hashtags, and SEO titles are
AI-GENERATED; the reviewer's job is tone-QA ("did the system misread
Braden's objectives? does the copy stay aggressive/clear in the right
direction?"), never writing metadata herself. So every piece of copy is
drafted here, attached to its asset, and posted INTO the Monday review
item — approve/reject is a judgment call on text that already exists.

The CopyPack schema doubles as the LLM structured-output contract and the
asset-attachment shape. `clips` is positional: entry i is the copy for the
i-th clip asset handed to the model.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ClipCopy(BaseModel):
    seo_title: str = Field(
        description="SEO-optimized YouTube Shorts title for this clip — "
        "punchy, keyword-forward, ≤90 chars, no clickbait that the clip "
        "doesn't pay off."
    )
    caption: str = Field(
        description="Social caption for this clip (Instagram/X) in the "
        "creator's voice. 1–3 sentences, hook first."
    )
    hashtags: list[str] = Field(
        default_factory=list,
        description="5–10 hashtags, no '#' prefix, ordered most-relevant "
        "first (platform-agnostic; publisher adds the '#').",
    )


class CopyPack(BaseModel):
    video_seo_title: str = Field(
        description="SEO title for the source video itself (used in "
        "announcements), ≤90 chars."
    )
    x_post: str = Field(
        description="One X/Twitter post announcing the drop, ≤240 chars "
        "(leave room for a link). Creator's voice, direct, no hashtag spam."
    )
    clips: list[ClipCopy] = Field(
        default_factory=list,
        description="Copy for each clip, in the SAME ORDER the clips were "
        "presented.",
    )


def hashtag_line(tags: list[str] | None) -> str:
    return " ".join(f"#{t.lstrip('#')}" for t in (tags or []) if t and t.strip())


def clip_copy_markdown(copy: dict) -> str:
    """Render one clip's copy for its Monday review item — what the
    reviewer tone-QAs."""
    lines = [
        f"**SEO title:** {copy.get('seo_title') or '—'}",
        f"**Caption:** {copy.get('caption') or '—'}",
    ]
    tags = hashtag_line(copy.get("hashtags"))
    if tags:
        lines.append(f"**Hashtags:** {tags}")
    lines.append("\n_QA the tone — approve if it reads like Braden, reject if it misses._")
    return "\n".join(lines)


def episode_copy_markdown(asset: dict) -> str:
    """Render the podcast episode's copy for its review item."""
    chapters = asset.get("chapters") or []
    chapter_rows = "\n".join(
        f"- {c.get('start')} — {c.get('title')}" for c in chapters
    )
    parts = [
        f"**Episode title:** {asset.get('title') or '—'}",
        f"**Summary:** {asset.get('summary') or '—'}",
        f"**Show notes:**\n{asset.get('description') or '—'}",
    ]
    if chapter_rows:
        parts.append(f"**Chapters:**\n{chapter_rows}")
    parts.append("\n_QA the tone — approve if it reads like Braden, reject if it misses._")
    return "\n\n".join(parts)


# ── Publish-time text builders (pure; publisher falls back gracefully) ─────

def shorts_title(clip_asset: dict, fallback: str) -> str:
    base = ((clip_asset.get("copy") or {}).get("seo_title") or clip_asset.get("title") or fallback).strip()
    suffix = " #Shorts"
    if base.lower().endswith("#shorts"):
        return base[:100]
    return (base[: 100 - len(suffix)] + suffix) if base else f"Clip{suffix}"


def shorts_description(clip_asset: dict, video_title: str) -> str:
    c = clip_asset.get("copy") or {}
    parts = [p for p in (c.get("caption"), hashtag_line(c.get("hashtags"))) if p]
    parts.append(f"From: {video_title}")
    return "\n\n".join(parts)


def ig_caption(clip_asset: dict, fallback: str) -> str:
    c = clip_asset.get("copy") or {}
    caption = (c.get("caption") or fallback).strip()
    tags = hashtag_line(c.get("hashtags"))
    return f"{caption}\n\n{tags}".strip() if tags else caption


def x_text(post_copy_asset: dict | None, video_title: str, links: list[str]) -> str:
    """The announcement tweet: the reviewer-approved drafted post when it
    exists, else a plain fallback. Link appended when there's room."""
    base = ((post_copy_asset or {}).get("x_post") or "").strip() or f"New drop: {video_title}"
    if links:
        candidate = f"{base}\n{links[0]}"
        return candidate if len(candidate) <= 280 else base[:280]
    return base[:280]


def post_copy_markdown(asset: dict) -> str:
    return (
        f"**X post:** {asset.get('x_post') or '—'}\n"
        f"**Video SEO title:** {asset.get('video_seo_title') or '—'}\n\n"
        "_QA the tone — approve to let this go out with the drop._"
    )
