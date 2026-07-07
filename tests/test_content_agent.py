"""
Content Agent (Agent #5) — interface + contract guards.

No real LLM, no network, no Supabase. Tests assert:
  - the agent instantiates and compiles its graph
  - the manifest is internally consistent and declares the two-step
    reviewer→owner approval chain (the Kaydi→Braden gate Phase C wires up)
  - intent routing falls back safely to general
  - the pipeline lane aborts cleanly when no video can be resolved
  - the YouTube-URL video-id extraction matches URLs but never bare words
  - the ledger helpers no-op in dev mode (no Supabase) instead of raising
  - the pipeline summary template renders from a ledger row dict
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.agents.content.agent import (
    ContentAgent,
    STUBBED_STAGES,
    VALID_INTENTS,
    _YT_URL_ID,
)
from packages.agents.content.tools import (
    fetch_recent_pipelines,
    get_content_tools,
    record_stage,
    set_pipeline_status,
    upsert_pipeline_row,
)
from packages.agents.core.templates import render

_AGENT_DIR = Path(__file__).resolve().parents[1] / "packages" / "agents" / "content"


# ── Graph / interface ──────────────────────────────────────────────────────
class TestAgentInterface:
    def test_instantiates_and_compiles(self):
        agent = ContentAgent()
        agent.graph.compile(interrupt_before=agent.interrupt_before_nodes)

    def test_required_attrs(self):
        agent = ContentAgent()
        assert agent.slug == "content"
        assert agent.name == "Content Agent"
        assert agent.description
        assert agent.model

    def test_no_interrupt_gates_yet(self):
        # Phase A has no publish node; the approval gate arrives with the
        # publish fan-out (Phase D) — but the CHAIN is already declared in
        # the manifest so the approvals runtime knows the shape.
        assert ContentAgent().interrupt_before_nodes == []

    def test_tools_roster(self):
        names = {t.name for t in get_content_tools()}
        assert names == {"get_pipeline_status"}


# ── Manifest truth ─────────────────────────────────────────────────────────
class TestManifest:
    @pytest.fixture
    def manifest(self) -> dict:
        return json.loads((_AGENT_DIR / "manifest.json").read_text(encoding="utf-8"))

    def test_basics(self, manifest):
        assert manifest["slug"] == "content"
        assert manifest["status"] == "active"
        assert "youtube" in manifest["required_integrations"]

    def test_declares_two_step_approval_chain(self, manifest):
        """The whole point of Agent #5's review flow: reviewer (first-line)
        THEN owner (final) — two ordered human gates before anything
        publishes."""
        assert manifest["approval_policy"]["approvers"] == ["reviewer", "owner"]

    def test_agent_resolves_chain_from_manifest(self):
        """BaseAgent reads approval_policy.approvers from the manifest next
        to the agent module — the orchestrator will create one approvals row
        per step, resuming the graph only after the FINAL approval."""
        assert ContentAgent().approval_chain({}) == ["reviewer", "owner"]


# ── Routing ────────────────────────────────────────────────────────────────
class TestRouting:
    def test_valid_intents(self):
        assert VALID_INTENTS == {"run_pipeline", "pipeline_status", "general"}

    @pytest.mark.parametrize("intent, expected", [
        ("run_pipeline", "run_pipeline"),
        ("pipeline_status", "pipeline_status"),
        ("general", "general"),
        ("RUN_PIPELINE", "run_pipeline"),
        ("nonsense", "general"),
        (None, "general"),
    ])
    def test_route_by_intent_falls_back_to_general(self, intent, expected):
        agent = ContentAgent()
        assert agent._route_by_intent({"intent": intent}) == expected

    def test_route_after_init_gates_on_pipeline_ready(self):
        agent = ContentAgent()
        assert agent._route_after_init({"metadata": {"pipeline_ready": True}}) == "proceed"
        assert agent._route_after_init({"metadata": {"pipeline_ready": False}}) == "abort"
        assert agent._route_after_init({"metadata": {}}) == "abort"


# ── Video-id extraction ────────────────────────────────────────────────────
class TestVideoIdExtraction:
    @pytest.mark.parametrize("text, expected", [
        ("process https://youtu.be/dQw4w9WgXcQ please", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=abc_-123XYZ", "abc_-123XYZ"),
        ("https://youtube.com/shorts/A1b2C3d4E5f", "A1b2C3d4E5f"),
        ("https://youtube.com/live/A1b2C3d4E5f?feature=share", "A1b2C3d4E5f"),
    ])
    def test_matches_youtube_urls(self, text, expected):
        m = _YT_URL_ID.search(text)
        assert m and m.group(1) == expected

    @pytest.mark.parametrize("text", [
        "the word consistency is exactly eleven letters",  # no bare-token match
        "run the pipeline on my latest video",
        "",
    ])
    def test_never_matches_bare_words(self, text):
        assert _YT_URL_ID.search(text) is None


# ── Pipeline lane behaviour (no Supabase → dev-mode no-ops) ────────────────
class TestPipelineLane:
    @pytest.mark.asyncio
    async def test_init_aborts_without_video(self):
        """Chat-initiated run with no link → ask for it, don't open a ledger
        row, and route to abort."""
        from langchain_core.messages import HumanMessage

        agent = ContentAgent()
        state = {
            "messages": [HumanMessage(content="run the pipeline")],
            "org_id": "dev",
            "metadata": {},
        }
        out = await agent._init_pipeline_node(state)
        assert out["metadata"]["pipeline_ready"] is False
        assert "link" in out["messages"][0].content.lower() or "video" in out["messages"][0].content.lower()

    @pytest.mark.asyncio
    async def test_stubbed_stages_mark_ledger_skipped(self):
        """Phase A stages record an honest 'skipped' with the phase that
        implements them — mirrored onto state.pipeline for the reply."""
        agent = ContentAgent()
        state = {
            "messages": [],
            "org_id": "dev",  # non-UUID → ledger writes no-op
            "video_id": "dQw4w9WgXcQ",
            "pipeline": {"video_id": "dQw4w9WgXcQ", "stages": {}, "assets": []},
            "metadata": {"pipeline_ready": True},
        }
        for stage in STUBBED_STAGES:
            out = await getattr(agent, f"_{stage}_node")(state)
            state["pipeline"] = out["pipeline"]
        assert set(state["pipeline"]["stages"]) == set(STUBBED_STAGES)
        assert all(v["status"] == "skipped" for v in state["pipeline"]["stages"].values())

    @pytest.mark.asyncio
    async def test_queue_review_fails_honestly_without_assets(self):
        agent = ContentAgent()
        state = {
            "messages": [],
            "org_id": "dev",
            "video_id": "dQw4w9WgXcQ",
            "pipeline": {"video_id": "dQw4w9WgXcQ", "stages": {}, "assets": []},
            "metadata": {"pipeline_ready": True},
        }
        out = await agent._queue_review_node(state)
        assert out["pipeline"]["status"] == "failed"
        assert "no assets" in out["pipeline"]["error"]


# ── Ledger helpers degrade gracefully in dev mode ──────────────────────────
class TestLedgerDevMode:
    def test_all_helpers_noop_without_supabase(self):
        # current_supabase is reset to None by the autouse fixture; "dev" is
        # not a real UUID. None of these may raise.
        assert upsert_pipeline_row("dev", "vid") is None
        record_stage("dev", "vid", "extract_audio", "done")
        set_pipeline_status("dev", "vid", "failed", error="x")
        assert fetch_recent_pipelines("dev") == []


# ── Template rendering ─────────────────────────────────────────────────────
class TestTemplates:
    def test_pipeline_summary_renders(self, langley_profile):
        pipeline = {
            "video_id": "dQw4w9WgXcQ",
            "video_title": "8PM Live — July 7",
            "status": "failed",
            "error": "no assets generated — the generation stages aren't implemented yet (Phase B)",
            "stages": {
                "extract_audio": {"status": "skipped", "detail": "ships in Phase B"},
            },
            "assets": [],
        }
        out = render("content", "pipeline_summary.j2", profile=langley_profile, pipeline=pipeline)
        assert "8PM Live — July 7" in out
        assert "extract audio" in out
        assert "{{" not in out and "{%" not in out

    def test_system_renders_for_each_intent(self, langley_profile):
        for intent in ("general", "pipeline_status", "run_pipeline"):
            out = render(
                "content", "system.j2",
                profile=langley_profile,
                intent=intent,
                peer_context={},
                podcast_brand="Positively American with Braden Langley",
                publish_deadline_local="12:00",
            )
            assert "{{" not in out and "{%" not in out
            if intent == "general":
                assert "two approvals" in out
