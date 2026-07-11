"""
Image Reader / Voice agent — interface + contract guards.

No real LLM, no model downloads, no Supabase. Tests assert:
  - the agent instantiates and compiles its graph
  - the manifest is internally consistent (manifest-truth style)
  - intent routing keys off attachments (image → read_image, audio →
    transcribe) without touching the LLM
  - the structured-output card only emits when analyze_image actually ran
  - the Markdown report renders from a structured analysis dict
  - transcription.py raises a CLEAR error (never silently empty) when no
    backend is configured — and does NOT import faster-whisper at module load
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from packages.agents.image_reader.agent import (
    ImageAnalysis,
    ImageReaderAgent,
    _content_has_image,
    _text_from_content,
)
from packages.agents.image_reader.tools import get_image_reader_tools
from packages.agents.core.templates import render


_AGENT_DIR = Path(__file__).resolve().parents[1] / "packages" / "agents" / "image_reader"


# ── Graph / interface ──────────────────────────────────────────────────────
class TestAgentInterface:
    def test_instantiates_and_compiles(self):
        agent = ImageReaderAgent()
        # Compiles with whatever interrupt_before it declares (none here).
        agent.graph.compile(interrupt_before=agent.interrupt_before_nodes)

    def test_required_attrs(self):
        agent = ImageReaderAgent()
        assert agent.slug == "image-reader"
        assert agent.name == "Image Reader"
        assert agent.description
        assert agent.model  # Sonnet for vision quality

    def test_no_interrupt_gates(self):
        # Reading and transcribing are read-only — no HITL.
        assert ImageReaderAgent().interrupt_before_nodes == []

    def test_tools_roster(self):
        # Vision is native and transcription is a node; the one LLM tool is
        # the middle-man delegation to other agents.
        assert {t.name for t in get_image_reader_tools()} == {"delegate_task"}


# ── Manifest truth ─────────────────────────────────────────────────────────
class TestManifest:
    def _manifest(self) -> dict:
        return json.loads((_AGENT_DIR / "manifest.json").read_text(encoding="utf-8"))

    def test_required_fields(self):
        m = self._manifest()
        for field in ("slug", "name", "description", "tagline", "icon", "tools", "writes"):
            assert field in m, f"manifest missing '{field}'"

    def test_slug_matches_agent(self):
        assert self._manifest()["slug"] == ImageReaderAgent.slug

    def test_tools_match_registered(self):
        # Empty in manifest must equal empty registered set.
        assert set(self._manifest().get("tools") or []) == {t.name for t in get_image_reader_tools()}

    def test_capabilities_declared(self):
        caps = self._manifest().get("capabilities") or []
        for cap in ("vision", "ocr", "analysis", "transcription"):
            assert cap in caps


# ── Intent routing (no LLM) ────────────────────────────────────────────────
class TestRouting:
    def _state(self, messages, metadata=None):
        return {"messages": messages, "metadata": metadata or {}, "org_id": "dev"}

    def test_image_block_detected(self):
        content = [
            {"type": "text", "text": "what does this show?"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "x"}},
        ]
        assert _content_has_image(content) is True
        assert _text_from_content(content) == "what does this show?"

    def test_image_url_block_detected(self):
        assert _content_has_image([{"type": "image_url", "image_url": {"url": "http://x"}}]) is True

    def test_plain_text_has_no_image(self):
        assert _content_has_image("just text") is False
        assert _content_has_image([{"type": "text", "text": "hi"}]) is False

    @pytest.mark.asyncio
    async def test_classify_routes_image_without_llm(self):
        """An image attachment short-circuits to read_image — the LLM
        classifier is never invoked (so this runs with no API key)."""
        agent = ImageReaderAgent()
        msg = HumanMessage(content=[
            {"type": "text", "text": "read this"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "x"}},
        ])
        out = await agent._classify_intent_node(self._state([msg]))
        assert out == {"intent": "read_image"}
        assert agent._route_by_intent({"intent": "read_image"}) == "read_image"

    @pytest.mark.asyncio
    async def test_classify_routes_audio_without_llm(self):
        agent = ImageReaderAgent()
        msg = HumanMessage(content="(voice note)")
        state = self._state([msg], metadata={"audio": {"bytes_b64": "abc", "content_type": "audio/ogg"}})
        out = await agent._classify_intent_node(state)
        assert out == {"intent": "transcribe"}

    def test_route_falls_back_to_general(self):
        agent = ImageReaderAgent()
        assert agent._route_by_intent({"intent": "nonsense"}) == "general"
        assert agent._route_by_intent({}) == "general"


# ── Structured output gating ───────────────────────────────────────────────
class TestStructuredOutputs:
    def test_analysis_emitted_when_node_ran(self):
        agent = ImageReaderAgent()
        state = {"analysis": {"title": "t", "summary": "s"}}
        out = agent.get_structured_outputs(
            state,
            ["load_profile", "load_peer_context", "classify_intent", "analyze_image", "persist_report", "respond"],
        )
        assert out == {"analysis": {"title": "t", "summary": "s"}}

    def test_analysis_not_emitted_when_node_did_not_run(self):
        agent = ImageReaderAgent()
        out = agent.get_structured_outputs(
            {"analysis": {"title": "stale"}},
            ["load_profile", "classify_intent", "general_answer", "respond"],
        )
        assert out == {}

    def test_analysis_not_emitted_when_absent(self):
        agent = ImageReaderAgent()
        assert agent.get_structured_outputs({}, ["analyze_image"]) == {}


# ── Report rendering ───────────────────────────────────────────────────────
class TestReportRender:
    def test_render_report_produces_markdown(self, langley_profile):
        agent = ImageReaderAgent()
        analysis = ImageAnalysis(
            title="YouTube analytics — 28d",
            summary="Views are up.",
            data_points=[{"label": "Views", "value": "120,000"}],
            analysis="Strong browse traffic.",
            recommendations=["Double down on the hook style"],
        ).model_dump(mode="json")
        state = {"metadata": {"profile": langley_profile.model_dump(mode="json")}, "org_id": "dev"}
        md = agent._render_report(state, analysis)
        assert md.startswith("# YouTube analytics — 28d")
        assert "| Views | 120,000 |" in md
        assert "## Analysis" in md
        assert "- Double down on the hook style" in md

    def test_report_template_renders_directly(self, langley_profile):
        out = render(
            "image_reader",
            "analysis_report.j2",
            profile=langley_profile,
            analysis={"title": "T", "summary": "", "data_points": [], "analysis": "A", "recommendations": []},
        )
        assert "# T" in out
        assert "## Analysis" in out
        assert "{{" not in out and "{%" not in out


# ── Transcription backend ──────────────────────────────────────────────────
class TestTranscription:
    @pytest.mark.asyncio
    async def test_empty_audio_raises_clear_error(self):
        from packages.agents.core.transcription import (
            TranscriptionUnavailable,
            transcribe_audio,
        )
        with pytest.raises(TranscriptionUnavailable):
            await transcribe_audio(b"")

    @pytest.mark.asyncio
    async def test_openai_backend_without_key_raises(self, monkeypatch):
        """The hosted backend must raise a clear error (never return empty)
        when its API key isn't configured."""
        from packages.agents.core import transcription as t

        monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(t.TranscriptionUnavailable) as exc:
            await t.transcribe_audio(b"\x00\x01", content_type="audio/ogg")
        assert "OPENAI_API_KEY" in str(exc.value)

    @pytest.mark.asyncio
    async def test_unknown_provider_raises(self, monkeypatch):
        from packages.agents.core import transcription as t

        monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "banana")
        with pytest.raises(t.TranscriptionUnavailable):
            await t.transcribe_audio(b"\x00\x01")

    @pytest.mark.asyncio
    async def test_local_backend_without_package_raises_clear_error(self, monkeypatch):
        """When TRANSCRIPTION_PROVIDER=local but faster-whisper isn't
        installed, surface a clear install hint — and crucially this never
        triggers a model download in the suite."""
        import builtins

        from packages.agents.core import transcription as t

        monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "local")
        real_import = builtins.__import__

        def _no_faster_whisper(name, *args, **kwargs):
            if name == "faster_whisper" or name.startswith("faster_whisper."):
                raise ImportError("simulated: faster-whisper not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_faster_whisper)
        with pytest.raises(t.TranscriptionUnavailable) as exc:
            await t.transcribe_audio(b"\x00\x01", content_type="audio/ogg")
        assert "faster-whisper" in str(exc.value)

    def test_module_does_not_import_faster_whisper_at_load(self):
        """faster-whisper is lazily imported — importing the module must not
        pull it in (and so never download a model just to load the package)."""
        import sys

        import packages.agents.core.transcription  # noqa: F401

        assert "faster_whisper" not in sys.modules
