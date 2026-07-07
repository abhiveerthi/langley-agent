"""
Content Agent Phase B — media acquisition, podcast helpers, and stage
behaviour. No network, no LLM, no Supabase:

  - Riverside recording matching (pure policy fn)
  - Opus Clip payload normalization + status mapping (pure)
  - acquire_audio fallback chain (Riverside → YouTube) via monkeypatching
  - podcast time helpers + transcript budgeting (pure)
  - run_extract_audio / run_generate_clips / run_draft_podcast degrade
    gracefully per the skipped/failed/done contract
  - transcription seam raises TranscriptionUnavailable, never silently
"""
from __future__ import annotations

import pytest

from packages.agents.content import media, stages
from packages.agents.content.podcast import (
    build_timed_transcript,
    episode_asset,
    hms_to_seconds,
    seconds_to_hms,
)
from packages.integrations.opusclip.client import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PROCESSING,
    _normalize_project,
    _normalize_status,
)
from packages.integrations.riverside.client import match_recording


# ── Riverside matching policy ──────────────────────────────────────────────
class TestRiversideMatching:
    def _rec(self, id, started_at, title="Daily Live", audio_url="https://a/x.mp3"):
        return {"id": id, "started_at": started_at, "title": title, "audio_url": audio_url}

    def test_matches_closest_within_window(self):
        recs = [
            self._rec("far", "2026-07-06T01:00:00Z"),
            self._rec("close", "2026-07-07T01:30:00Z"),
        ]
        got = match_recording("8PM Live", "2026-07-07T02:00:00Z", recs)
        assert got["id"] == "close"

    def test_no_match_outside_window(self):
        recs = [self._rec("old", "2026-07-05T02:00:00Z")]
        assert match_recording("8PM Live", "2026-07-07T02:00:00Z", recs) is None

    def test_recordings_without_audio_never_match(self):
        recs = [self._rec("mute", "2026-07-07T02:00:00Z", audio_url=None)]
        assert match_recording("8PM Live", "2026-07-07T02:00:00Z", recs) is None

    def test_title_fallback_without_publish_time(self):
        recs = [
            self._rec("a", None, title="Morning prep session"),
            self._rec("b", None, title="Positively American July 7 live"),
        ]
        got = match_recording("Positively American — July 7 LIVE", None, recs)
        assert got["id"] == "b"

    def test_empty_inputs(self):
        assert match_recording("t", "2026-07-07T00:00:00Z", []) is None
        assert match_recording(None, None, [self._rec("x", None, title="")]) is None


# ── Opus Clip normalization ────────────────────────────────────────────────
class TestOpusNormalization:
    @pytest.mark.parametrize("raw, expected", [
        ("completed", STATUS_DONE),
        ("DONE", STATUS_DONE),
        ("failed", STATUS_FAILED),
        ("cancelled", STATUS_FAILED),
        ("processing", STATUS_PROCESSING),
        ("queued", STATUS_PROCESSING),
        (None, STATUS_PROCESSING),
    ])
    def test_status_mapping(self, raw, expected):
        assert _normalize_status(raw) == expected

    def test_normalizes_nested_project_and_clips(self):
        payload = {
            "project": {
                "project_id": "p1",
                "state": "completed",
                "outputs": [
                    {"video_url": "https://c/1.mp4", "name": "Hook", "duration": "34.5"},
                    {"title": "no-url clip is dropped"},
                ],
            }
        }
        got = _normalize_project(payload)
        assert got["id"] == "p1"
        assert got["status"] == STATUS_DONE
        assert got["clips"] == [
            {"url": "https://c/1.mp4", "title": "Hook", "duration_seconds": 34.5}
        ]


# ── acquire_audio fallback chain ───────────────────────────────────────────
class TestAcquireAudio:
    @pytest.mark.asyncio
    async def test_falls_back_to_youtube_when_riverside_unconfigured(self, monkeypatch):
        async def fake_yt(video_id):
            return b"yt-bytes", "audio/mp4"

        monkeypatch.setattr(media, "download_youtube_audio", fake_yt)
        # RIVERSIDE_API_KEY unset in tests → is_configured() False
        got = await media.acquire_audio("vid1", video_title="t", published_at=None)
        assert got["source"] == "youtube"
        assert got["bytes"] == b"yt-bytes"

    @pytest.mark.asyncio
    async def test_prefers_riverside_when_it_matches(self, monkeypatch):
        import packages.integrations.riverside as rs

        monkeypatch.setattr(rs, "is_configured", lambda: True)

        async def fake_find(title, published_at):
            return {"id": "r1", "audio_url": "https://a/x.mp3"}

        async def fake_download(rec, *, max_bytes):
            assert max_bytes > 0  # production must pass the byte budget
            return b"studio-bytes", "audio/mpeg"

        monkeypatch.setattr(rs, "find_recording_for_video", fake_find)
        monkeypatch.setattr(rs, "download_audio", fake_download)
        got = await media.acquire_audio("vid1", video_title="t", published_at="2026-07-07T02:00:00Z")
        assert got["source"] == "riverside"
        assert got["bytes"] == b"studio-bytes"

    @pytest.mark.asyncio
    async def test_riverside_error_demotes_to_youtube(self, monkeypatch):
        import packages.integrations.riverside as rs

        monkeypatch.setattr(rs, "is_configured", lambda: True)

        async def boom(title, published_at):
            raise rs.RiversideError("500")

        async def fake_yt(video_id):
            return b"yt-bytes", "audio/mp4"

        monkeypatch.setattr(rs, "find_recording_for_video", boom)
        monkeypatch.setattr(media, "download_youtube_audio", fake_yt)
        got = await media.acquire_audio("vid1")
        assert got["source"] == "youtube"

    @pytest.mark.asyncio
    async def test_raises_unavailable_when_no_source_works(self, monkeypatch):
        async def no_ytdlp(video_id):
            raise media.AudioExtractionUnavailable("yt-dlp missing")

        monkeypatch.setattr(media, "download_youtube_audio", no_ytdlp)
        with pytest.raises(media.AudioExtractionUnavailable) as ei:
            await media.acquire_audio("vid1")
        # The error narrates the whole chain, not just the last hop.
        assert "riverside" in str(ei.value).lower()
        assert "yt-dlp" in str(ei.value)


# ── Podcast helpers ────────────────────────────────────────────────────────
class TestPodcastHelpers:
    @pytest.mark.parametrize("sec, hms", [
        (0, "00:00:00"),
        (61, "00:01:01"),
        (3723.9, "01:02:03"),
    ])
    def test_seconds_to_hms(self, sec, hms):
        assert seconds_to_hms(sec) == hms

    @pytest.mark.parametrize("hms, sec", [
        ("00:00:00", 0),
        ("01:02:03", 3723),
        ("12:34", 754),
        ("garbage", 0),
        (None, 0),
    ])
    def test_hms_to_seconds(self, hms, sec):
        assert hms_to_seconds(hms) == sec

    def test_timed_transcript_lines(self):
        segs = [
            {"start": 0, "end": 4, "text": "Welcome back."},
            {"start": 65, "end": 70, "text": "First topic."},
            {"start": 0, "end": 1, "text": "   "},  # blank text dropped
        ]
        out = build_timed_transcript(segs)
        assert out.splitlines() == ["[00:00:00] Welcome back.", "[00:01:05] First topic."]

    def test_timed_transcript_samples_evenly_over_budget(self):
        segs = [
            {"start": i * 10, "end": i * 10 + 5, "text": f"segment number {i} content"}
            for i in range(1000)
        ]
        out = build_timed_transcript(segs, char_budget=2000)
        lines = out.splitlines()
        assert len(out) <= 2000
        # Coverage must span the episode, not just its head.
        assert lines[0].startswith("[00:00:00]")
        last_start = lines[-1].split("]")[0].lstrip("[")
        assert hms_to_seconds(last_start) > 5000

    def test_episode_asset_shape(self):
        asset = episode_asset(
            {"title": "Ep", "summary": "s", "description": "d",
             "chapters": [{"start": "00:00:00", "title": "Open"}]},
            audio_asset={"storage_path": "org/audio/x.m4a", "content_type": "audio/mp4", "size_bytes": 5},
            podcast_brand="Positively American with Braden Langley",
            video_id="vid1",
        )
        assert asset["kind"] == "podcast_episode"
        assert asset["brand"].startswith("Positively American")
        assert asset["audio_storage_path"] == "org/audio/x.m4a"


# ── Stage behaviour (ledger contract) ──────────────────────────────────────
def _pipeline_state(**extra) -> dict:
    return {
        "messages": [],
        "org_id": "dev",  # non-UUID → ledger writes no-op
        "video_id": "vid1",
        "video_title": "8PM Live",
        "pipeline": {"video_id": "vid1", "stages": {}, "assets": []},
        "metadata": {"pipeline_ready": True},
        **extra,
    }


class TestStages:
    @pytest.mark.asyncio
    async def test_extract_audio_skips_when_no_source(self, monkeypatch):
        async def unavailable(video_id, **kw):
            raise media.AudioExtractionUnavailable("nothing configured")

        monkeypatch.setattr(stages, "acquire_audio", unavailable)
        out = await stages.run_extract_audio(_pipeline_state())
        assert out["pipeline"]["stages"]["extract_audio"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_extract_audio_done_with_transcription_note(self, monkeypatch):
        async def fake_acquire(video_id, **kw):
            return {"bytes": b"x" * 2048, "content_type": "audio/mp4", "source": "youtube"}

        async def fake_segments(audio_bytes, *, content_type=None):
            from packages.agents.core.transcription import TranscriptionUnavailable
            raise TranscriptionUnavailable("no backend")

        monkeypatch.setattr(stages, "acquire_audio", fake_acquire)
        monkeypatch.setattr(stages, "transcribe_audio_segments", fake_segments)
        out = await stages.run_extract_audio(_pipeline_state())
        stage = out["pipeline"]["stages"]["extract_audio"]
        assert stage["status"] == "done"  # audio still shipped
        assert "transcription unavailable" in stage["detail"]
        assert out["audio_asset"]["kind"] == "audio"
        assert out["transcript_segments"] is None

    @pytest.mark.asyncio
    async def test_generate_clips_skips_unconfigured(self):
        # OPUSCLIP_API_KEY unset in the test env → is_configured() False.
        out = await stages.run_generate_clips(_pipeline_state())
        stage = out["pipeline"]["stages"]["generate_clips"]
        assert stage["status"] == "skipped"
        assert "OPUSCLIP_API_KEY" in stage["detail"]

    @pytest.mark.asyncio
    async def test_generate_clips_done(self, monkeypatch):
        import packages.integrations.opusclip as opus

        monkeypatch.setattr(opus, "is_configured", lambda: True)

        async def fake_submit(url):
            return {"id": "p1", "status": "processing", "clips": []}

        async def fake_wait(pid, *, timeout_seconds):
            return {"id": "p1", "status": "done", "clips": [
                {"url": "https://c/1.mp4", "title": "Hook", "duration_seconds": 30.0}
            ]}

        monkeypatch.setattr(opus, "submit_clip_project", fake_submit)
        monkeypatch.setattr(opus, "wait_for_project", fake_wait)
        out = await stages.run_generate_clips(_pipeline_state())
        assert out["pipeline"]["stages"]["generate_clips"]["status"] == "done"
        assert out["clip_assets"][0]["kind"] == "clip"
        assert out["clip_assets"][0]["source"] == "opusclip"

    @pytest.mark.asyncio
    async def test_generate_clips_records_timeout_as_failed(self, monkeypatch):
        import packages.integrations.opusclip as opus

        monkeypatch.setattr(opus, "is_configured", lambda: True)

        async def fake_submit(url):
            return {"id": "p1", "status": "processing", "clips": []}

        async def timeout(pid, *, timeout_seconds):
            raise opus.OpusClipTimeout("still processing after 1800s")

        monkeypatch.setattr(opus, "submit_clip_project", fake_submit)
        monkeypatch.setattr(opus, "wait_for_project", timeout)
        out = await stages.run_generate_clips(_pipeline_state())
        stage = out["pipeline"]["stages"]["generate_clips"]
        assert stage["status"] == "failed"
        assert "1800s" in stage["detail"]

    @pytest.mark.asyncio
    async def test_draft_podcast_skips_without_transcript(self):
        out = await stages.run_draft_podcast(
            _pipeline_state(transcript_segments=None), llm=None, profile=None
        )
        stage = out["pipeline"]["stages"]["draft_podcast"]
        assert stage["status"] == "skipped"
        assert "no transcript" in stage["detail"]


    @pytest.mark.asyncio
    async def test_extract_audio_failed_branch(self, monkeypatch):
        """A real error (not 'nothing configured') must record FAILED — the
        skipped/failed distinction is the ledger's honesty contract."""
        async def boom(video_id, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(stages, "acquire_audio", boom)
        out = await stages.run_extract_audio(_pipeline_state())
        stage = out["pipeline"]["stages"]["extract_audio"]
        assert stage["status"] == "failed"
        assert "network down" in stage["detail"]

    @pytest.mark.asyncio
    async def test_extract_audio_empty_transcript_nulls_segments(self, monkeypatch):
        async def fake_acquire(video_id, **kw):
            return {"bytes": b"x" * 100, "content_type": "audio/mp4", "source": "youtube"}

        async def empty_segments(audio_bytes, *, content_type=None):
            return []

        monkeypatch.setattr(stages, "acquire_audio", fake_acquire)
        monkeypatch.setattr(stages, "transcribe_audio_segments", empty_segments)
        out = await stages.run_extract_audio(_pipeline_state())
        assert out["transcript_segments"] is None
        assert "empty" in out["pipeline"]["stages"]["extract_audio"]["detail"]


class _FakeStructuredLLM:
    """Stands in for ChatAnthropic: with_structured_output returns self and
    ainvoke returns the canned PodcastEpisode, capturing the messages."""

    def __init__(self, result):
        self._result = result
        self.messages = None

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return self._result


class TestDraftPodcast:
    @pytest.mark.asyncio
    async def test_happy_path_renders_prompt_and_builds_asset(self, langley_profile):
        """Exercises the real template render (draft_podcast.j2 +
        podcast_episode.j2 under StrictUndefined), the podcast_brand
        fallback, and the episode asset wiring — with the LLM faked."""
        from packages.agents.content.podcast import ChapterMarker, PodcastEpisode

        episode = PodcastEpisode(
            title="The July 7th Rundown",
            description="Tonight we cover the big three stories.",
            summary="One sentence.",
            chapters=[ChapterMarker(start="00:00:00", title="Cold open")],
        )
        llm = _FakeStructuredLLM(episode)
        state = _pipeline_state(
            transcript_segments=[
                {"start": 0, "end": 4, "text": "Welcome back."},
                {"start": 120, "end": 125, "text": "Story one."},
            ],
            audio_asset={"kind": "audio", "storage_path": "p", "content_type": "audio/mp4", "size_bytes": 9},
        )
        out = await stages.run_draft_podcast(state, llm=llm, profile=langley_profile)

        stage = out["pipeline"]["stages"]["draft_podcast"]
        assert stage["status"] == "done"
        assert "The July 7th Rundown" in stage["detail"]
        asset = out["episode"]
        assert asset["kind"] == "podcast_episode"
        # No podcast_brand configured (dev org) → branded fallback from profile.
        assert asset["brand"] == f"The {langley_profile.brand.name} Podcast"
        assert asset["audio_storage_path"] == "p"
        assert asset["chapters"] == [{"start": "00:00:00", "title": "Cold open"}]
        # The timed transcript actually reached the model.
        human = llm.messages[-1].content
        assert "[00:00:00] Welcome back." in human
        assert "[00:02:00] Story one." in human

    @pytest.mark.asyncio
    async def test_llm_failure_records_failed(self, langley_profile):
        class _Boom:
            def with_structured_output(self, schema):
                return self

            async def ainvoke(self, messages):
                raise RuntimeError("model unavailable")

        state = _pipeline_state(transcript_segments=[{"start": 0, "end": 1, "text": "hi"}])
        out = await stages.run_draft_podcast(state, llm=_Boom(), profile=langley_profile)
        stage = out["pipeline"]["stages"]["draft_podcast"]
        assert stage["status"] == "failed"
        assert "model unavailable" in stage["detail"]


class TestOpusWaitLoop:
    @pytest.mark.asyncio
    async def test_wait_completes_on_done(self, monkeypatch):
        import packages.integrations.opusclip.client as oc

        states = iter(["processing", "done"])

        async def fake_get(pid):
            s = next(states)
            clips = [{"url": "https://c/1.mp4", "title": "", "duration_seconds": 30.0}] if s == "done" else []
            return {"id": pid, "status": s, "clips": clips, "error": None}

        monkeypatch.setattr(oc, "get_project", fake_get)
        got = await oc.wait_for_project("p1", timeout_seconds=60, poll_seconds=0)
        assert got["status"] == "done"
        assert got["clips"]

    @pytest.mark.asyncio
    async def test_wait_raises_error_on_failed_project(self, monkeypatch):
        import packages.integrations.opusclip.client as oc

        async def fake_get(pid):
            return {"id": pid, "status": "failed", "clips": [], "error": "bad source"}

        monkeypatch.setattr(oc, "get_project", fake_get)
        with pytest.raises(oc.OpusClipError, match="bad source"):
            await oc.wait_for_project("p1", timeout_seconds=60, poll_seconds=0)

    @pytest.mark.asyncio
    async def test_wait_times_out_on_wall_clock(self, monkeypatch):
        import packages.integrations.opusclip.client as oc

        async def fake_get(pid):
            return {"id": pid, "status": "processing", "clips": [], "error": None}

        monkeypatch.setattr(oc, "get_project", fake_get)
        with pytest.raises(oc.OpusClipTimeout):
            await oc.wait_for_project("p1", timeout_seconds=0, poll_seconds=0)


class TestPipelineSummaryWithRealAssets:
    def test_renders_audio_asset_without_title_key(self, langley_profile):
        """Regression guard: the audio asset descriptor has NO 'title' key,
        and the summary template runs under StrictUndefined — rendering the
        real shape must not raise."""
        from packages.agents.core.templates import render

        pipeline = {
            "video_id": "vid1",
            "video_title": "8PM Live",
            "status": "ready_for_review",
            "error": None,
            "stages": {"extract_audio": {"status": "done", "detail": "youtube audio, 42.0MB"}},
            "assets": [
                {"kind": "audio", "storage_path": "org/audio/x.m4a",
                 "content_type": "audio/mp4", "size_bytes": 44040192,
                 "source": "youtube", "video_id": "vid1"},
                {"kind": "podcast_episode", "title": "Ep 1"},
            ],
        }
        out = render("content", "pipeline_summary.j2", profile=langley_profile, pipeline=pipeline)
        assert "audio" in out
        assert "podcast_episode: Ep 1" in out


# ── Transcription seam ─────────────────────────────────────────────────────
class TestTranscriptionSegments:
    @pytest.mark.asyncio
    async def test_openai_without_key_raises_unavailable(self, monkeypatch):
        from packages.agents.core.transcription import (
            TranscriptionUnavailable,
            transcribe_audio_segments,
        )

        monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(TranscriptionUnavailable):
            await transcribe_audio_segments(b"xx", content_type="audio/mp4")

    @pytest.mark.asyncio
    async def test_unknown_provider_raises_unavailable(self, monkeypatch):
        from packages.agents.core.transcription import (
            TranscriptionUnavailable,
            transcribe_audio_segments,
        )

        monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "banana")
        with pytest.raises(TranscriptionUnavailable):
            await transcribe_audio_segments(b"xx")
