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
        return {"pipeline": record_and_mirror(state, "extract_audio", "failed", repr(e))}

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
    )
    try:
        structured = llm.with_structured_output(PodcastEpisode)
        episode: PodcastEpisode = await structured.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=timed_transcript),
        ])
    except Exception as e:
        log.exception("draft_podcast LLM call failed for %s", video_id)
        return {"pipeline": record_and_mirror(
            state, "draft_podcast", "failed", f"episode drafting failed: {e!r}"
        )}

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
