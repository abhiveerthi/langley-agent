"""
B-Roll Producer agent — interface + contract guards.

No real LLM, no Higgsfield network calls, no Supabase. Tests assert:
  - the agent instantiates and compiles its graph
  - the manifest is internally consistent (manifest-truth style:
    manifest.tools == get_broll_tools names)
  - intent routing falls back safely to general
  - the BRollPlan / BRollScript structured models validate
  - the Markdown plan renders from a structured plan dict
  - the Higgsfield client degrades GRACEFULLY (clear HiggsfieldUnavailable
    signal) when HIGGSFIELD_API_KEY is unset — WITHOUT any live network call
  - the Dropbox foldering organizes by date & topic
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.agents.broll.agent import (
    BRollAgent,
    BRollPlan,
    BRollScript,
)
from packages.agents.broll.tools import (
    broll_folder_path,
    deposit_clip_to_dropbox,
    get_broll_tools,
)
from packages.agents.core.templates import render


_AGENT_DIR = Path(__file__).resolve().parents[1] / "packages" / "agents" / "broll"


# ── Graph / interface ──────────────────────────────────────────────────────
class TestAgentInterface:
    def test_instantiates_and_compiles(self):
        agent = BRollAgent()
        agent.graph.compile(interrupt_before=agent.interrupt_before_nodes)

    def test_required_attrs(self):
        agent = BRollAgent()
        assert agent.slug == "broll"
        assert agent.name == "B-Roll Producer"
        assert agent.description
        assert agent.model  # Sonnet for scripting quality

    def test_no_interrupt_gates(self):
        # Drafting is read-only; generation/deposit are creator-initiated.
        assert BRollAgent().interrupt_before_nodes == []

    def test_has_generate_tool(self):
        names = {t.name for t in get_broll_tools()}
        assert names == {"generate_broll_clip"}


# ── Manifest truth ─────────────────────────────────────────────────────────
class TestManifest:
    def _manifest(self) -> dict:
        return json.loads((_AGENT_DIR / "manifest.json").read_text(encoding="utf-8"))

    def test_required_fields(self):
        m = self._manifest()
        for field in ("slug", "name", "description", "tagline", "icon", "tools", "writes"):
            assert field in m, f"manifest missing '{field}'"

    def test_slug_matches_agent(self):
        assert self._manifest()["slug"] == BRollAgent.slug

    def test_tools_match_registered(self):
        assert set(self._manifest().get("tools") or []) == {t.name for t in get_broll_tools()}

    def test_capabilities_declared(self):
        caps = self._manifest().get("capabilities") or []
        for cap in ("scripting", "video-generation", "organization"):
            assert cap in caps

    def test_optional_integrations(self):
        assert self._manifest().get("optional_integrations") == ["dropbox"]
        assert self._manifest().get("required_integrations") == []


# ── Intent routing (no LLM) ────────────────────────────────────────────────
class TestRouting:
    def test_route_known_intents(self):
        agent = BRollAgent()
        assert agent._route_by_intent({"intent": "draft_broll"}) == "draft_broll"
        assert agent._route_by_intent({"intent": "generate_broll"}) == "generate_broll"
        assert agent._route_by_intent({"intent": "general"}) == "general"

    def test_route_falls_back_to_general(self):
        agent = BRollAgent()
        assert agent._route_by_intent({"intent": "nonsense"}) == "general"
        assert agent._route_by_intent({}) == "general"


# ── Structured output gating ───────────────────────────────────────────────
class TestStructuredOutputs:
    def test_plan_emitted_when_node_ran(self):
        agent = BRollAgent()
        state = {"plan": {"title": "t", "summary": "s", "clips": []}}
        out = agent.get_structured_outputs(
            state,
            ["load_profile", "load_peer_context", "classify_intent", "draft_scripts", "persist_script", "respond"],
        )
        assert out == {"plan": {"title": "t", "summary": "s", "clips": []}}

    def test_plan_not_emitted_when_node_did_not_run(self):
        agent = BRollAgent()
        out = agent.get_structured_outputs(
            {"plan": {"title": "stale"}},
            ["load_profile", "classify_intent", "general_answer", "respond"],
        )
        assert out == {}

    def test_plan_not_emitted_when_absent(self):
        agent = BRollAgent()
        assert agent.get_structured_outputs({}, ["draft_scripts"]) == {}


# ── Structured models ──────────────────────────────────────────────────────
class TestModels:
    def test_script_validates_with_defaults(self):
        s = BRollScript(prompt="A clown slips on a banana peel", topic="Comedy")
        assert s.aspect_ratio == "16:9"
        assert s.duration_seconds == 6
        assert s.topic == "Comedy"

    def test_plan_validates(self):
        plan = BRollPlan(
            title="B-roll — June batch",
            summary="Interrupt-style beats.",
            clips=[
                {"prompt": "A football kicker misses wide", "aspect_ratio": "9:16", "duration_seconds": 8, "topic": "Sports"},
            ],
        )
        assert len(plan.clips) == 1
        assert plan.clips[0].aspect_ratio == "9:16"
        assert plan.clips[0].duration_seconds == 8


# ── Plan rendering ─────────────────────────────────────────────────────────
class TestPlanRender:
    def test_render_plan_produces_markdown(self, langley_profile):
        agent = BRollAgent()
        plan = BRollPlan(
            title="B-roll — June batch",
            summary="Interrupt-style beats for the week.",
            clips=[
                BRollScript(prompt="A clown slips dramatically", aspect_ratio="16:9",
                            duration_seconds=6, topic="Comedy", rationale="Comedic interrupt"),
            ],
        ).model_dump(mode="json")
        state = {"metadata": {"profile": langley_profile.model_dump(mode="json")}, "org_id": "dev"}
        md = agent._render_plan(state, plan)
        assert md.startswith("# B-roll — June batch")
        assert "A clown slips dramatically" in md
        assert "16:9" in md

    def test_plan_template_renders_directly(self, langley_profile):
        out = render(
            "broll",
            "broll_plan.j2",
            profile=langley_profile,
            plan={"title": "T", "summary": "", "clips": []},
        )
        assert "# T" in out
        assert "{{" not in out and "{%" not in out


# ── Higgsfield verified API contract (docs.higgsfield.ai, July 2026) ────────
class TestHiggsfieldContract:
    def test_requires_the_full_credential_pair(self, monkeypatch):
        from packages.integrations.higgsfield import client as h

        assert h.is_configured() is False  # conftest scrubs both
        monkeypatch.setenv("HIGGSFIELD_API_KEY", "uuid-key")
        assert h.is_configured() is False  # key alone is NOT configured
        monkeypatch.setenv("HIGGSFIELD_API_SECRET", "hexsecret")
        assert h.is_configured() is True

    def test_auth_header_is_key_colon_secret(self, monkeypatch):
        """The verified scheme: `Authorization: Key {key}:{secret}` — one
        header, the literal word Key. NOT Bearer."""
        from packages.integrations.higgsfield import client as h

        monkeypatch.setenv("HIGGSFIELD_API_KEY", "uuid-key")
        monkeypatch.setenv("HIGGSFIELD_API_SECRET", "hexsecret")
        headers = h._headers()
        assert headers["Authorization"] == "Key uuid-key:hexsecret"

    def test_missing_secret_names_what_is_missing(self, monkeypatch):
        from packages.integrations.higgsfield import client as h

        monkeypatch.setenv("HIGGSFIELD_API_KEY", "uuid-key")
        with pytest.raises(h.HiggsfieldUnavailable) as exc:
            h._credentials()
        assert "HIGGSFIELD_API_SECRET" in str(exc.value)

    @pytest.mark.parametrize("status, outcome", [
        ("completed", "success"),
        ("failed", "failure"),
        ("nsfw", "failure"),
        ("canceled", "failure"),
        ("queued", "pending"),
        ("in_progress", "pending"),
        ("some_future_status", "pending"),  # unknown = keep polling
        ("", "pending"),
    ])
    def test_status_classification(self, status, outcome):
        from packages.integrations.higgsfield import client as h

        assert h.classify_status(status) == outcome

    def test_result_extraction_video_then_images(self):
        from packages.integrations.higgsfield import client as h

        assert h.extract_result_url({"video": {"url": "https://v.mp4"}}) == "https://v.mp4"
        assert h.extract_result_url({"images": [{"url": "https://i.png"}]}) == "https://i.png"
        assert h.extract_result_url({"status": "completed"}) is None

    def test_error_mapping_actionable(self):
        from packages.integrations.higgsfield import client as h

        assert "credits" in str(h._error_for_response(403, "", what="submit"))
        assert "credentials" in str(h._error_for_response(401, "", what="submit"))
        assert "422" in str(h._error_for_response(422, "detail", what="submit"))


# ── Higgsfield graceful degradation (no network) ───────────────────────────
class TestHiggsfieldDegradation:
    def test_not_configured_without_key(self, monkeypatch):
        from packages.integrations.higgsfield import client as h

        monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
        assert h.is_configured() is False

    @pytest.mark.asyncio
    async def test_generate_clip_raises_clear_unavailable(self, monkeypatch):
        """With no key, generate_clip raises HiggsfieldUnavailable — a clear,
        catchable signal — before any HTTP call is made."""
        from packages.integrations.higgsfield import (
            HiggsfieldUnavailable,
            generate_clip,
        )

        monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
        with pytest.raises(HiggsfieldUnavailable) as exc:
            await generate_clip("a clown slips", aspect_ratio="16:9", duration_seconds=6)
        assert "HIGGSFIELD_API_KEY" in str(exc.value)

    @pytest.mark.asyncio
    async def test_tool_returns_status_not_configured(self, monkeypatch):
        """The LLM tool swallows HiggsfieldUnavailable and returns a clear
        status string so a run never crashes on a missing key."""
        from packages.agents.broll.tools import generate_broll_clip

        monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
        result = await generate_broll_clip.ainvoke(
            {"prompt": "a clown slips", "aspect_ratio": "16:9", "duration_seconds": 6}
        )
        assert "not configured" in result.lower()

    @pytest.mark.asyncio
    async def test_generate_node_degrades_without_key(self, monkeypatch, langley_profile):
        """The generate_clips node reports a clear status (no crash) when no
        key is set, even with a real plan on state."""
        from langchain_core.messages import AIMessage

        monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
        agent = BRollAgent()
        state = {
            "messages": [],
            "org_id": "dev",
            "metadata": {"profile": langley_profile.model_dump(mode="json")},
            "plan": {"title": "t", "summary": "s", "clips": [
                {"prompt": "p", "aspect_ratio": "16:9", "duration_seconds": 6, "topic": "X"},
            ]},
        }
        out = await agent._generate_clips_node(state)
        msgs = out.get("messages") or []
        assert msgs and isinstance(msgs[0], AIMessage)
        assert "configured" in msgs[0].content.lower()


# ── Dropbox foldering ──────────────────────────────────────────────────────
class TestDropboxFoldering:
    def test_folder_path_by_date_and_topic(self):
        path = broll_folder_path("Conservative Commentary", date="2026-06-15")
        assert path == "/B-Roll/2026-06-15/Conservative-Commentary"

    def test_folder_path_sanitizes_topic(self):
        path = broll_folder_path("weird/../topic name!", date="2026-06-15")
        # Slashes are stripped so a malicious topic can't escape its folder —
        # the topic is exactly one path segment under the dated folder.
        assert path.startswith("/B-Roll/2026-06-15/")
        topic_seg = path[len("/B-Roll/2026-06-15/"):]
        assert "/" not in topic_seg

    def test_folder_path_defaults_date(self):
        path = broll_folder_path("Sports")
        # /B-Roll/<YYYY-MM-DD>/Sports
        parts = path.strip("/").split("/")
        assert parts[0] == "B-Roll"
        assert len(parts[1]) == 10 and parts[1].count("-") == 2
        assert parts[2] == "Sports"

    @pytest.mark.asyncio
    async def test_deposit_noop_without_supabase(self):
        """No Supabase in context → best-effort no-op (returns None, no raise)."""
        result = await deposit_clip_to_dropbox(
            "dev", filename="clip.mp4", clip_bytes=b"x", topic="Sports"
        )
        assert result is None
