"""
Content Agent clarifications — routing policy, copy drafting, escalation.

Covers the client's extra specs:
  - live ≥30min → podcast; long-forms → Opus only; 8–10min → no podcast;
    Shorts → nothing; unknown duration → conservative (clips only)
  - AI-drafted copy attaches per-clip + a [Post] asset; stages gate on
    routing flags; publish-time text builders fall back gracefully
  - escalation is config-gated and never raises
"""
from __future__ import annotations

import pytest

from packages.agents.content import stages
from packages.agents.content.copy import (
    clip_copy_markdown,
    hashtag_line,
    ig_caption,
    shorts_description,
    shorts_title,
    x_text,
)
from packages.agents.content.routing import classify_video, podcast_min_seconds


# ── Routing policy ─────────────────────────────────────────────────────────
class TestRouting:
    @pytest.mark.parametrize(
        "duration_s, is_live, kind, podcast, clips",
        [
            (55 * 60, True, "live", True, True),      # nightly stream → podcast + clips
            (31 * 60, True, "live", True, True),      # just over threshold
            (20 * 60, True, "live", False, True),     # short live → clips only
            (45 * 60, False, "longform", False, True), # long-form → Opus, NOT podcast
            (9 * 60, False, "longform", False, True),  # 8–10min → never podcast
            (45, False, "short", False, False),        # a Short → nothing
            (60, True, "short", False, False),         # live-tagged but short-form
            (None, False, "longform", False, True),    # unknown → conservative
            (None, True, "live", False, True),         # unknown live → still no podcast
        ],
    )
    def test_matrix(self, duration_s, is_live, kind, podcast, clips):
        # podcast_enabled on: the matrix expresses the length/kind rules.
        got = classify_video(
            duration_seconds=duration_s, is_live=is_live,
            config={"podcast_enabled": True},
        )
        assert got["video_kind"] == kind
        assert got["podcast_eligible"] is podcast
        assert got["clips_eligible"] is clips
        assert got["reason"]

    def test_podcast_lane_paused_by_default(self):
        # 2026-08-06 client call: podcast production paused until his PR
        # consultant sets strategy — without podcast_enabled, even the
        # nightly 55-min live stream must NOT enter the podcast lane.
        got = classify_video(duration_seconds=55 * 60, is_live=True)
        assert got["podcast_eligible"] is False
        assert got["clips_eligible"] is True
        assert "paused" in got["reason"]
        got = classify_video(
            duration_seconds=55 * 60, is_live=True, config={"podcast_enabled": False}
        )
        assert got["podcast_eligible"] is False

    def test_threshold_configurable(self):
        assert podcast_min_seconds({"podcast_min_minutes": 45}) == 45 * 60
        assert podcast_min_seconds({}) == 30 * 60
        assert podcast_min_seconds({"podcast_min_minutes": "garbage"}) == 30 * 60
        got = classify_video(
            duration_seconds=40 * 60, is_live=True, config={"podcast_min_minutes": 45}
        )
        assert got["podcast_eligible"] is False


# ── Stage gating on routing ────────────────────────────────────────────────
def _state(routing, **extra):
    return {
        "messages": [], "org_id": "dev", "video_id": "v1", "video_title": "t",
        "pipeline": {"video_id": "v1", "stages": {}, "assets": []},
        "routing": routing, "metadata": {}, **extra,
    }


class TestStageRoutingGates:
    @pytest.mark.asyncio
    async def test_extract_audio_skips_non_podcast_video(self):
        routing = {"podcast_eligible": False, "clips_eligible": True, "reason": "long-form routes to Opus Clip, not podcast creation"}
        out = await stages.run_extract_audio(_state(routing))
        stage = out["pipeline"]["stages"]["extract_audio"]
        assert stage["status"] == "skipped"
        assert "routing" in stage["detail"]

    @pytest.mark.asyncio
    async def test_generate_clips_skips_shorts(self):
        routing = {"podcast_eligible": False, "clips_eligible": False, "reason": "already short-form — no clipping, no podcast"}
        out = await stages.run_generate_clips(_state(routing))
        stage = out["pipeline"]["stages"]["generate_clips"]
        assert stage["status"] == "skipped"
        assert "short-form" in stage["detail"]

    @pytest.mark.asyncio
    async def test_draft_podcast_skips_by_routing_before_transcript_check(self):
        routing = {"podcast_eligible": False, "clips_eligible": True, "reason": "live stream under 30min — clips only"}
        out = await stages.run_draft_podcast(
            _state(routing, transcript_segments=[{"start": 0, "end": 1, "text": "hi"}]),
            llm=None, profile=None,
        )
        stage = out["pipeline"]["stages"]["draft_podcast"]
        assert stage["status"] == "skipped"
        assert "routing" in stage["detail"]


# ── draft_copy stage ───────────────────────────────────────────────────────
class _FakeCopyLLM:
    def __init__(self, pack):
        self._pack = pack
        self.messages = None

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return self._pack


class TestDraftCopy:
    @pytest.mark.asyncio
    async def test_attaches_copy_positionally_and_builds_post_asset(self, langley_profile):
        from packages.agents.content.copy import ClipCopy, CopyPack

        pack = CopyPack(
            video_seo_title="Braden Breaks Down the Big Three",
            x_post="Tonight's episode is live. No fluff.",
            clips=[ClipCopy(seo_title="The Truth About X", caption="He said it.", hashtags=["2a", "news"])],
        )
        llm = _FakeCopyLLM(pack)
        state = _state(
            {"podcast_eligible": True, "clips_eligible": True, "reason": "r"},
            clip_assets=[
                {"kind": "clip", "url": "https://c/1.mp4", "title": "clip one"},
                {"kind": "clip", "url": "https://c/2.mp4", "title": "clip two"},  # no copy returned
            ],
        )
        out = await stages.run_draft_copy(state, llm=llm, profile=langley_profile)
        assert out["pipeline"]["stages"]["draft_copy"]["status"] == "done"
        clips = out["clip_assets"]
        assert clips[0]["copy"]["seo_title"] == "The Truth About X"
        assert "copy" not in clips[1]  # model under-delivered → fallback later
        assert out["post_copy"]["kind"] == "post_copy"
        assert out["post_copy"]["x_post"].startswith("Tonight's")
        # The clip list actually reached the model, in order.
        assert "Clip 1: clip one" in llm.messages[-1].content

    @pytest.mark.asyncio
    async def test_skips_with_nothing_to_write(self, langley_profile):
        state = _state({"podcast_eligible": True, "clips_eligible": True, "reason": "r"})
        out = await stages.run_draft_copy(state, llm=None, profile=langley_profile)
        assert out["pipeline"]["stages"]["draft_copy"]["status"] == "skipped"


# ── Publish-time text builders ─────────────────────────────────────────────
class TestCopyBuilders:
    def test_shorts_title_uses_seo_then_falls_back(self):
        assert shorts_title({"copy": {"seo_title": "SEO"}}, "fb") == "SEO #Shorts"
        assert shorts_title({"title": "Clip T"}, "fb") == "Clip T #Shorts"
        assert shorts_title({}, "fb") == "fb #Shorts"
        long = "x" * 150
        assert len(shorts_title({"copy": {"seo_title": long}}, "fb")) <= 100

    def test_descriptions_and_captions(self):
        clip = {"copy": {"caption": "Hook.", "hashtags": ["a", "#b"]}}
        assert "Hook." in shorts_description(clip, "Vid")
        assert "#a #b" in shorts_description(clip, "Vid")
        assert "From: Vid" in shorts_description(clip, "Vid")
        assert ig_caption(clip, "fb") == "Hook.\n\n#a #b"
        assert ig_caption({}, "fb") == "fb"

    def test_hashtag_line_normalizes(self):
        assert hashtag_line(["a", "#b", "", None]) == "#a #b"
        assert hashtag_line(None) == ""

    def test_x_text_prefers_drafted_post_and_respects_280(self):
        assert x_text({"x_post": "Drafted."}, "Vid", ["https://l"]) == "Drafted.\nhttps://l"
        assert x_text(None, "Vid", []) == "New drop: Vid"
        long_post = "y" * 279
        assert x_text({"x_post": long_post}, "Vid", ["https://longlink"]) == long_post[:280]

    def test_clip_copy_markdown_mentions_qa(self):
        md = clip_copy_markdown({"seo_title": "T", "caption": "C", "hashtags": ["h"]})
        assert "SEO title" in md and "QA the tone" in md


# ── Escalation gate ────────────────────────────────────────────────────────
class TestEscalation:
    @pytest.mark.asyncio
    async def test_noop_without_channel_config(self, mock_supabase_factory, real_uuid):
        from packages.agents.content.alerts import escalate

        sb = mock_supabase_factory({"agents": [{"slug": "content", "config": {}}]})
        assert await escalate(real_uuid, "boom", supabase=sb) is False

    @pytest.mark.asyncio
    async def test_noop_in_dev_mode(self):
        from packages.agents.content.alerts import escalate

        assert await escalate("dev", "boom") is False

    @pytest.mark.asyncio
    async def test_sends_when_configured(self, mock_supabase_factory, real_uuid, monkeypatch):
        from packages.agents.content import alerts
        from packages.integrations.slack import client as slack_client

        sb = mock_supabase_factory({
            "agents": [{"slug": "content", "config": {"escalation_slack_channel_id": "C123"}}],
            "integrations": [{"provider": "slack", "access_token": "xoxb", "status": "active"}],
        })
        sent = []

        async def fake_post(token, channel, text):
            sent.append((channel, text))
            return {"ok": True}

        monkeypatch.setattr(slack_client, "post_message", fake_post)
        assert await alerts.escalate(real_uuid, "Opus Clip is down", supabase=sb) is True
        assert sent and sent[0][0] == "C123"
        assert "Opus Clip is down" in sent[0][1]
