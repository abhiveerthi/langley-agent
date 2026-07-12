"""
Agent #6 (Image Reader / Voice) — Slack surface + clarification features.

No live Slack, no LLM, no Supabase. Covers:
  - the events filter now admits file_share messages (screenshots/voice
    notes have no text and a subtype — the old filter dropped them)
  - file splitting by mimetype; image content-block assembly with caps
  - the voice transcription chain (whisper-first, Slack preview fallback)
  - window parsing + report-archive helpers for compile_report
  - the delegate_task tool contract (roster gate, task creation, dev no-op)
  - schema additions (trends, competitor_position) validate
"""
from __future__ import annotations

import pytest

from app.routers.slack_events import _is_user_message
from app.services import slack_runner


# ── Events filter ──────────────────────────────────────────────────────────
class TestEventsFilter:
    def test_plain_text_message_accepted(self):
        assert _is_user_message({"type": "message", "user": "U1", "text": "hi"})

    def test_file_share_with_files_accepted_even_without_text(self):
        event = {
            "type": "message", "subtype": "file_share", "user": "U1",
            "text": "", "files": [{"id": "F1", "mimetype": "image/png"}],
        }
        assert _is_user_message(event)

    def test_file_share_without_files_rejected(self):
        assert not _is_user_message(
            {"type": "message", "subtype": "file_share", "user": "U1", "text": ""}
        )

    @pytest.mark.parametrize("event", [
        {"type": "message", "subtype": "message_changed", "user": "U1", "text": "x"},
        {"type": "message", "bot_id": "B1", "subtype": "file_share",
         "user": "U1", "files": [{"id": "F1"}]},
        {"type": "reaction_added", "user": "U1"},
    ])
    def test_noise_still_rejected(self, event):
        assert not _is_user_message(event)


# ── DM routing (front door) ────────────────────────────────────────────────
class TestDmRouting:
    def test_mapped_channel_wins(self):
        route = slack_runner.resolve_route(
            {"org_id": "o1", "agent_slug": "publisher"}, "im", {"org_id": "o1"}
        )
        assert route == ("o1", "publisher")

    def test_unmapped_dm_routes_to_image_reader(self):
        route = slack_runner.resolve_route(None, "im", {"org_id": "o1", "access_token": "x"})
        assert route == ("o1", slack_runner.DM_AGENT_SLUG)

    def test_unmapped_non_dm_ignored(self):
        assert slack_runner.resolve_route(None, "group", {"org_id": "o1"}) is None
        assert slack_runner.resolve_route(None, None, {"org_id": "o1"}) is None

    def test_dm_without_install_org_ignored(self):
        assert slack_runner.resolve_route(None, "im", {"access_token": "x"}) is None
        assert slack_runner.resolve_route(None, "im", None) is None


# ── File splitting + image blocks ──────────────────────────────────────────
class TestFileHandling:
    def test_split_files(self):
        files = [
            {"mimetype": "image/png", "id": "F1"},
            {"mimetype": "audio/mp4", "id": "F2"},
            {"mimetype": "", "subtype": "slack_audio", "id": "F3"},  # voice clip
            {"mimetype": "application/pdf", "id": "F4"},
        ]
        images, audios = slack_runner._split_files(files)
        assert [f["id"] for f in images] == ["F1"]
        assert [f["id"] for f in audios] == ["F2", "F3"]

    @pytest.mark.asyncio
    async def test_image_blocks_cap_and_skip(self, monkeypatch):
        async def fake_download(token, url, *, max_bytes):
            if "big" in url:
                raise RuntimeError("Slack file exceeds 5MB cap")
            return b"png-bytes"

        monkeypatch.setattr(slack_runner.slack_client, "download_file", fake_download)
        files = [
            {"name": f"s{i}.png", "mimetype": "image/png",
             "url_private_download": f"https://files/s{i}"}
            for i in range(5)
        ] + [{"name": "big.png", "mimetype": "image/png",
              "url_private_download": "https://files/big"}]

        blocks, skipped = await slack_runner._image_content_blocks(
            "xoxb", files, "what changed?"
        )
        image_blocks = [b for b in blocks if b["type"] == "image"]
        assert len(image_blocks) == slack_runner.MAX_IMAGES_PER_MESSAGE
        assert blocks[0] == {"type": "text", "text": "what changed?"}
        assert image_blocks[0]["source"]["type"] == "base64"
        assert image_blocks[0]["source"]["media_type"] == "image/png"
        # one over the count cap + one over the byte cap
        assert len(skipped) == 2

    @pytest.mark.asyncio
    async def test_image_blocks_empty_when_nothing_survives(self, monkeypatch):
        async def always_too_big(token, url, *, max_bytes):
            raise RuntimeError("too big")

        monkeypatch.setattr(slack_runner.slack_client, "download_file", always_too_big)
        blocks, skipped = await slack_runner._image_content_blocks(
            "xoxb", [{"name": "x.png", "mimetype": "image/png",
                      "url_private_download": "https://f/x"}], "",
        )
        assert blocks == []
        assert skipped


# ── Voice transcription chain ──────────────────────────────────────────────
class TestVoiceChain:
    def _file(self, **over):
        return {
            "id": "F9", "mimetype": "audio/mp4",
            "url_private_download": "https://files/voice", **over,
        }

    @pytest.mark.asyncio
    async def test_whisper_first(self, monkeypatch):
        async def fake_download(token, url, *, max_bytes):
            return b"audio"

        async def fake_transcribe(audio_bytes, *, content_type=None):
            return "the full accurate transcript"

        monkeypatch.setattr(slack_runner.slack_client, "download_file", fake_download)
        import packages.agents.core.transcription as tr

        monkeypatch.setattr(tr, "transcribe_audio", fake_transcribe)
        transcript, note = await slack_runner._transcribe_slack_audio("xoxb", self._file())
        assert transcript == "the full accurate transcript"
        assert note == "whisper"

    @pytest.mark.asyncio
    async def test_slack_preview_fallback_when_whisper_unavailable(self, monkeypatch):
        async def fake_download(token, url, *, max_bytes):
            return b"audio"

        async def unavailable(audio_bytes, *, content_type=None):
            from packages.agents.core.transcription import TranscriptionUnavailable
            raise TranscriptionUnavailable("no backend")

        monkeypatch.setattr(slack_runner.slack_client, "download_file", fake_download)
        import packages.agents.core.transcription as tr

        monkeypatch.setattr(tr, "transcribe_audio", unavailable)
        file = self._file(transcription={
            "status": "complete", "preview": {"content": "slack's own transcript"},
        })
        transcript, note = await slack_runner._transcribe_slack_audio("xoxb", file)
        assert transcript == "slack's own transcript"
        assert "slack-native" in note

    @pytest.mark.asyncio
    async def test_no_transcript_returns_none_with_reason(self, monkeypatch):
        async def fake_download(token, url, *, max_bytes):
            return b"audio"

        async def unavailable(audio_bytes, *, content_type=None):
            from packages.agents.core.transcription import TranscriptionUnavailable
            raise TranscriptionUnavailable("no backend configured")

        async def no_info(token, file_id):
            return {}

        monkeypatch.setattr(slack_runner.slack_client, "download_file", fake_download)
        monkeypatch.setattr(slack_runner.slack_client, "get_file_info", no_info)
        import packages.agents.core.transcription as tr

        monkeypatch.setattr(tr, "transcribe_audio", unavailable)
        transcript, note = await slack_runner._transcribe_slack_audio("xoxb", self._file())
        assert transcript is None
        assert "no backend" in note


# ── compile_report helpers ─────────────────────────────────────────────────
class TestReportWindow:
    @pytest.mark.parametrize("text, days", [
        ("give me the 60 day report", 60),
        ("compile the last 30 days", 30),
        ("45-day rollup please", 45),
        ("compile the report", 30),          # default
        ("the 3 day report", 7),              # clamped up
        ("the 500 day report", 90),           # clamped down
        (None, 30),
    ])
    def test_parse_window_days(self, text, days):
        from packages.agents.image_reader.tools import parse_window_days

        assert parse_window_days(text) == days

    def test_fetch_reports_dev_noop(self):
        from packages.agents.image_reader.tools import fetch_recent_image_reports

        assert fetch_recent_image_reports("dev", 30) == []


# ── delegate_task tool ─────────────────────────────────────────────────────
class TestDelegateTask:
    @pytest.mark.asyncio
    async def test_rejects_unknown_agent(self):
        from packages.agents.image_reader.tools import delegate_task

        out = await delegate_task.ainvoke(
            {"agent_slug": "editor-in-chief", "instruction": "do a thing"}
        )
        assert "isn't a delegatable agent" in out

    @pytest.mark.asyncio
    async def test_delegates_via_task_creation(self, monkeypatch, real_uuid):
        import packages.agents.core.tasks as tasks_mod
        from packages.agents.image_reader import tools as ir_tools
        from packages.integrations.context import current_org_id

        created = []

        async def fake_create(**kwargs):
            created.append(kwargs)
            return "task-123"

        monkeypatch.setattr(tasks_mod, "create_task_from_agent", fake_create)
        current_org_id.set(real_uuid)
        out = await ir_tools.delegate_task.ainvoke(
            {"agent_slug": "strategist", "instruction": "Fold today's competitor read into the brief"}
        )
        assert "task-123" in out
        assert created[0]["agent_slug"] == "strategist"
        assert created[0]["metadata"]["delegated_by"] == "image-reader"

    @pytest.mark.asyncio
    async def test_dev_noop_reports_skip(self):
        from packages.agents.image_reader.tools import delegate_task
        from packages.integrations.context import current_org_id

        current_org_id.set("dev")
        out = await delegate_task.ainvoke(
            {"agent_slug": "strategist", "instruction": "x"}
        )
        assert "Couldn't create the task" in out


# ── Review-pass regression guards ──────────────────────────────────────────
class TestSlackFileHostGate:
    @pytest.mark.parametrize("url, ok", [
        ("https://files.slack.com/files-pri/T1-F1/x.png", True),
        ("https://myteam.slack.com/x.png", True),
        ("https://a.slack-edge.com/x.png", True),
        ("https://evil.com/files.slack.com/x.png", False),
        ("https://slack.com.evil.com/x.png", False),
        ("http://files.slack.com/x.png", False),  # https only
        ("", False),
    ])
    def test_host_allowlist(self, url, ok):
        from packages.integrations.slack.client import _is_slack_file_host

        assert _is_slack_file_host(url) is ok

    @pytest.mark.asyncio
    async def test_download_refuses_foreign_host(self):
        from packages.integrations.slack.client import download_file

        with pytest.raises(RuntimeError, match="non-Slack"):
            await download_file("xoxb-secret", "https://evil.example/f", max_bytes=100)


class TestUnsupportedImageTypes:
    @pytest.mark.asyncio
    async def test_heic_skipped_with_actionable_note(self, monkeypatch):
        async def fake_download(token, url, *, max_bytes):
            return b"bytes"

        monkeypatch.setattr(slack_runner.slack_client, "download_file", fake_download)
        blocks, skipped = await slack_runner._image_content_blocks(
            "xoxb",
            [{"name": "photo.heic", "mimetype": "image/heic",
              "url_private_download": "https://files.slack.com/p"}],
            "read this",
        )
        assert blocks == []  # nothing survived → caller won't run the agent
        assert skipped and "PNG/JPEG/WebP" in skipped[0]


class TestRespondStaleAnalysisGuard:
    @pytest.mark.asyncio
    async def test_fresh_ai_message_wins_over_persisted_analysis(self):
        """A compiled report (or any assistant reply) must not get the
        previous turn's image analysis re-rendered after it."""
        from langchain_core.messages import AIMessage, HumanMessage
        from packages.agents.image_reader.agent import ImageReaderAgent

        agent = ImageReaderAgent()
        state = {
            "messages": [
                HumanMessage(content="compile the 30-day report"),
                AIMessage(content="# 30-day research report\n..."),
            ],
            "analysis": {"title": "STALE turn-1 analysis"},  # persisted channel
            "metadata": {},
            "org_id": "dev",
        }
        out = await agent._respond_node(state)
        assert "research report" in out["messages"][0].content
        assert "STALE" not in out["messages"][0].content


class TestReportFetchFilters:
    def test_excludes_compiled_reports_and_reads_chronologically(
        self, mock_supabase_factory, real_uuid
    ):
        from packages.agents.image_reader.tools import fetch_recent_image_reports
        from packages.integrations.context import current_supabase

        sb = mock_supabase_factory({
            "storage_assets": [
                {"storage_path": "p3", "filename": "image-analysis-3.md", "created_at": "2026-07-10"},
                {"storage_path": "pr", "filename": "research-report-30d-x.md", "created_at": "2026-07-09"},
                {"storage_path": "p1", "filename": "image-analysis-1.md", "created_at": "2026-07-01"},
            ],
        })
        current_supabase.set(sb)
        rows = fetch_recent_image_reports(real_uuid, 30)
        names = [r["filename"] for r in rows]
        assert "research-report-30d-x.md" not in names  # no self-recursion
        # reversed(newest-first canned order) → chronological
        assert names == ["image-analysis-1.md", "image-analysis-3.md"]


# ── Schema additions ───────────────────────────────────────────────────────
class TestSchema:
    def test_trend_and_competitor_fields_validate(self):
        from packages.agents.image_reader.agent import ImageAnalysis, TrendInsight

        analysis = ImageAnalysis(
            title="Competitor scan",
            summary="s",
            analysis="a",
            trends=[TrendInsight(metric="Monthly views", direction="up",
                                 assessment="3-month climb, real momentum")],
            competitor_position="Braden leads on engagement, trails on subs.",
        )
        dumped = analysis.model_dump()
        assert dumped["trends"][0]["direction"] == "up"
        assert dumped["competitor_position"].startswith("Braden")
        # Old payloads (no new fields) still validate — additive change.
        ImageAnalysis(title="t", summary="s", analysis="a")
