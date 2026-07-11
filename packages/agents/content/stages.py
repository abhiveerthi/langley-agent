"""
Content Agent pipeline stages — the real Phase B implementations.

Each `run_*` function is the body of one graph node in agent.py. They all
follow the same contract:

  - Take the graph state (plus the LLM/profile where drafting needs it).
  - Do the work with graceful degradation: an unconfigured integration
    records the stage as "skipped" with the reason; a real failure records
    "failed"; success records "done". The pipeline NEVER crashes because a
    key is missing — that's the Higgsfield posture, applied pipeline-wide.
  - Write the outcome to the durable ledger (record_stage) AND mirror it
    onto state.pipeline for the chat reply / FE card.
  - Return a LangGraph state-update dict.

Kept out of agent.py so the graph/routing layer stays readable and under
the repo's file-size ceiling; kept as free functions so tests can drive
them with plain dicts and monkeypatched integrations — no graph, no LLM.
"""
from __future__ import annotations

import logging
import os

from langchain_core.messages import HumanMessage, SystemMessage

from packages.agents.core.templates import render
from packages.agents.core.transcription import (
    TranscriptionUnavailable,
    transcribe_audio_segments,
)
from packages.agents.content.media import (
    AudioExtractionUnavailable,
    acquire_audio,
    store_audio_asset,
)
from packages.agents.content.podcast import (
    PodcastEpisode,
    build_timed_transcript,
    episode_asset,
)
from packages.agents.content.tools import load_agent_config, record_stage

log = logging.getLogger("content.stages")


async def _escalate_failure(state: dict, stage: str, detail: str) -> None:
    """Route a stage FAILURE (not a routing skip) to the owner's Slack —
    he monitors Slack and fixes outages himself; the reviewer's Monday
    board stays free of operational noise. Best-effort."""
    from packages.agents.content.alerts import escalate

    title = state.get("video_title") or state.get("video_id") or "?"
    try:
        await escalate(state.get("org_id") or "", f"{stage} failed for '{title}': {detail}")
    except Exception:  # pragma: no cover — alerts must never cascade
        log.warning("escalation attempt itself failed for %s", stage)

# Bounded wait for Opus Clip's server-side processing. The pipeline runs in
# a background task (see scheduler._dispatch_content), so a long wait only
# occupies that task — never the poll sweep.
DEFAULT_CLIP_WAIT_SECONDS = 1800


def record_and_mirror(
    state: dict, stage: str, status: str, detail: str | None = None
) -> dict:
    """Write one stage outcome to the ledger and return the updated
    state.pipeline mirror. `detail` is capped to keep ledger rows readable."""
    detail = (detail or None) and str(detail)[:300]
    record_stage(
        state.get("org_id") or "",
        state.get("video_id") or "",
        stage,
        status,
        detail,
    )
    pipeline = dict(state.get("pipeline") or {})
    stages = dict(pipeline.get("stages") or {})
    stages[stage] = {"status": status, "detail": detail}
    pipeline["stages"] = stages
    return pipeline


# ── Stage: extract_audio ────────────────────────────────────────────────────

async def run_extract_audio(state: dict) -> dict:
    """Acquire podcast source audio (Riverside-preferred, YouTube fallback),
    archive it, and transcribe it with timestamps for the drafting stage.

    Transcription failure downgrades gracefully: the audio asset still ships
    (it's independently valuable), the stage records the transcription note,
    and draft_podcast will skip itself for lack of a transcript.
    """
    video_id = state.get("video_id") or ""

    routing = state.get("routing") or {}
    if not routing.get("podcast_eligible", True):
        return {"pipeline": record_and_mirror(
            state, "extract_audio", "skipped",
            f"routing: {routing.get('reason') or 'not podcast-eligible'}",
        )}

    try:
        audio = await acquire_audio(
            video_id,
            video_title=state.get("video_title"),
            published_at=state.get("published_at"),
        )
    except AudioExtractionUnavailable as e:
        return {"pipeline": record_and_mirror(state, "extract_audio", "skipped", str(e))}
    except Exception as e:
        log.exception("extract_audio failed for %s", video_id)
        detail = repr(e)
        await _escalate_failure(state, "extract_audio", detail)
        return {"pipeline": record_and_mirror(state, "extract_audio", "failed", detail)}

    asset = await store_audio_asset(
        state.get("org_id") or "",
        video_id,
        audio_bytes=audio["bytes"],
        content_type=audio["content_type"],
        source=audio["source"],
        video_title=state.get("video_title"),
    )

    segments: list[dict] | None
    note = ""
    try:
        segments = await transcribe_audio_segments(
            audio["bytes"], content_type=audio["content_type"]
        )
        if not segments:
            segments = None
            note = "; transcript came back empty"
    except TranscriptionUnavailable as e:
        segments = None
        note = f"; transcription unavailable: {e}"
    except Exception as e:
        log.exception("transcription failed for %s", video_id)
        segments = None
        note = f"; transcription failed: {e!r}"

    size_mb = asset["size_bytes"] / (1024 * 1024)
    detail = f"{audio['source']} audio, {size_mb:.1f}MB{note}"
    return {
        "pipeline": record_and_mirror(state, "extract_audio", "done", detail),
        "audio_asset": asset,
        "transcript_segments": segments,
    }


# ── Stage: generate_clips ───────────────────────────────────────────────────

async def run_generate_clips(state: dict) -> dict:
    """Submit the upload to Opus Clip and collect the finished clips.

    Not configured → skipped (the team keeps clipping manually until a key
    lands). Configured but failed/timed out → failed with the reason; a
    timed-out Opus project may still finish server-side and gets pulled when
    the video is retried.
    """
    from packages.integrations import opusclip

    video_id = state.get("video_id") or ""

    routing = state.get("routing") or {}
    if not routing.get("clips_eligible", True):
        return {"pipeline": record_and_mirror(
            state, "generate_clips", "skipped",
            f"routing: {routing.get('reason') or 'not clip-eligible'}",
        )}

    if not opusclip.is_configured():
        return {"pipeline": record_and_mirror(
            state, "generate_clips", "skipped",
            "Opus Clip not configured (set OPUSCLIP_API_KEY to enable auto-clipping)",
        )}

    try:
        project = await opusclip.submit_clip_project(
            f"https://www.youtube.com/watch?v={video_id}"
        )
        timeout = int(os.environ.get("CONTENT_CLIP_WAIT_SECONDS", str(DEFAULT_CLIP_WAIT_SECONDS)))
        result = await opusclip.wait_for_project(project["id"], timeout_seconds=timeout)
    except opusclip.OpusClipUnavailable as e:
        return {"pipeline": record_and_mirror(state, "generate_clips", "skipped", str(e))}
    except opusclip.OpusClipError as e:  # includes OpusClipTimeout
        await _escalate_failure(state, "generate_clips (Opus Clip)", str(e))
        return {"pipeline": record_and_mirror(state, "generate_clips", "failed", str(e))}

    clips = [
        {
            "kind": "clip",
            "url": c["url"],
            "title": c.get("title") or "",
            "duration_seconds": c.get("duration_seconds"),
            "source": "opusclip",
            "video_id": video_id,
        }
        for c in result.get("clips") or []
    ]
    if not clips:
        return {"pipeline": record_and_mirror(
            state, "generate_clips", "failed",
            f"Opus project {result.get('id')} finished but returned no clips",
        )}
    return {
        "pipeline": record_and_mirror(
            state, "generate_clips", "done", f"{len(clips)} clip(s) from Opus"
        ),
        "clip_assets": clips,
    }


# ── Stage: draft_podcast ────────────────────────────────────────────────────

async def run_draft_podcast(state: dict, *, llm, profile) -> dict:
    """Draft the episode (title, show notes, chapters) from the timestamped
    transcript, under the org's configured podcast brand."""
    video_id = state.get("video_id") or ""

    routing = state.get("routing") or {}
    if not routing.get("podcast_eligible", True):
        return {"pipeline": record_and_mirror(
            state, "draft_podcast", "skipped",
            f"routing: {routing.get('reason') or 'not podcast-eligible'}",
        )}

    segments = state.get("transcript_segments")
    if not segments:
        return {"pipeline": record_and_mirror(
            state, "draft_podcast", "skipped",
            "no transcript available — audio extraction or transcription didn't produce one",
        )}

    config = load_agent_config(state.get("org_id") or "")
    podcast_brand = (config.get("podcast_brand") or "").strip() or (
        f"The {profile.brand.name} Podcast"
    )

    timed_transcript = build_timed_transcript(segments)
    system_prompt = render(
        "content",
        "draft_podcast.j2",
        profile=profile,
        podcast_brand=podcast_brand,
        video_title=state.get("video_title") or video_id,
        copy_style_guide=(config.get("copy_style_guide") or "").strip(),
        creative_direction=(state.get("creative_direction") or "").strip(),
    )
    try:
        structured = llm.with_structured_output(PodcastEpisode)
        episode: PodcastEpisode = await structured.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=timed_transcript),
        ])
    except Exception as e:
        log.exception("draft_podcast LLM call failed for %s", video_id)
        detail = f"episode drafting failed: {e!r}"
        await _escalate_failure(state, "draft_podcast", detail)
        return {"pipeline": record_and_mirror(state, "draft_podcast", "failed", detail)}

    asset = episode_asset(
        episode,
        audio_asset=state.get("audio_asset"),
        podcast_brand=podcast_brand,
        video_id=video_id,
    )

    # Best-effort human-readable show-notes export to the Storage Library.
    try:
        from packages.agents.core.storage_export import export_to_storage

        md = render(
            "content",
            "podcast_episode.j2",
            profile=profile,
            episode=episode.model_dump(),
            podcast_brand=podcast_brand,
        )
        await export_to_storage(
            org_id=state.get("org_id") or "",
            agent_slug="content",
            kind="script",
            filename=f"{video_id}-episode.md",
            content=md,
            mime_type="text/markdown",
            source_id=video_id,
            tags=["content-pipeline", "podcast-episode"],
        )
    except Exception as e:
        log.warning("show-notes export failed for %s: %r", video_id, e)

    detail = f"episode '{episode.title}' with {len(episode.chapters)} chapter(s)"
    return {
        "pipeline": record_and_mirror(state, "draft_podcast", "done", detail),
        "episode": asset,
    }


# ── Stage: draft_copy ───────────────────────────────────────────────────────

async def run_draft_copy(state: dict, *, llm, profile) -> dict:
    """AI-drafted SEO/social copy for everything the run produced: an SEO
    title + caption + hashtags per clip, and the drop's X post. The
    reviewer tone-QAs this text on the Monday board — she never writes
    metadata herself (product clarification #1/#2).

    Honors the org's `copy_style_guide` config and the run's
    `creative_direction` (the creator's free-form steer when he re-runs a
    video whose tone came out wrong)."""
    from packages.agents.content.copy import CopyPack

    video_id = state.get("video_id") or ""
    clips = [dict(c) for c in (state.get("clip_assets") or [])]
    episode = state.get("episode")

    if not clips and not episode:
        return {"pipeline": record_and_mirror(
            state, "draft_copy", "skipped", "no assets produced — nothing to write copy for",
        )}

    config = load_agent_config(state.get("org_id") or "")
    video_title = state.get("video_title") or video_id
    system_prompt = render(
        "content",
        "draft_copy.j2",
        profile=profile,
        video_title=video_title,
        has_transcript=bool(state.get("transcript_segments")),
        copy_style_guide=(config.get("copy_style_guide") or "").strip(),
        creative_direction=(state.get("creative_direction") or "").strip(),
    )
    clip_lines = "\n".join(
        f"Clip {i + 1}: {c.get('title') or 'untitled'}"
        f" ({int(c.get('duration_seconds') or 0)}s)"
        for i, c in enumerate(clips)
    ) or "(no clips this run)"
    human = (
        f"Video: {video_title}\n\nClips to write copy for, in order:\n{clip_lines}"
    )

    try:
        structured = llm.with_structured_output(CopyPack)
        pack: CopyPack = await structured.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human),
        ])
    except Exception as e:
        log.exception("draft_copy LLM call failed for %s", video_id)
        detail = f"copy drafting failed: {e!r}"
        await _escalate_failure(state, "draft_copy", detail)
        return {"pipeline": record_and_mirror(state, "draft_copy", "failed", detail)}

    # Positional attach; a short model response leaves trailing clips
    # without copy (publisher falls back to the clip title).
    for i, clip in enumerate(clips):
        if i < len(pack.clips):
            clip["copy"] = pack.clips[i].model_dump()

    post_copy = {
        "kind": "post_copy",
        "x_post": pack.x_post,
        "video_seo_title": pack.video_seo_title,
        "video_id": video_id,
    }

    detail = f"copy for {min(len(clips), len(pack.clips))} clip(s) + announcement post"
    return {
        "pipeline": record_and_mirror(state, "draft_copy", "done", detail),
        "clip_assets": clips,
        "post_copy": post_copy,
    }
