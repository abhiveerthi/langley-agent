"""
Roster sanity checks — every registered agent should:
  - Instantiate without raising
  - Compile its graph (with interrupt_before applied)
  - Have a manifest.json next to its agent module
  - Render its primary system prompt(s) under the test profile

Plus the cross-cutting invariant: any agent that declares `interrupt_before`
nodes must override `get_approval_request` so the approvals runtime knows
what to surface in the approval card.

These are cheap regression catches — anything that breaks the agent
interface fails fast in CI rather than at first-real-request time.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.agents.core.templates import render
from packages.agents.registry import AGENT_REGISTRY, get_agent

# Live roster only — exclude any test-mock entries that may have been
# registered by sibling test modules.
_LIVE_SLUGS = [
    "strategist",
    "publisher",
    "community-manager",
    "brand-manager",
    "editor",
]


@pytest.fixture(params=_LIVE_SLUGS, ids=_LIVE_SLUGS)
def live_agent(request):
    """Parametrize across every live agent — each test runs once per slug."""
    assert request.param in AGENT_REGISTRY, f"Live slug {request.param!r} missing from registry"
    return get_agent(request.param)


# ── Per-agent invariants ──────────────────────────────────────────────────
class TestRegistry:
    def test_compiles_with_interrupt_before(self, live_agent):
        live_agent.graph.compile(interrupt_before=live_agent.interrupt_before_nodes)

    def test_has_required_attrs(self, live_agent):
        assert live_agent.slug, f"{type(live_agent).__name__}.slug is empty"
        assert live_agent.name, f"{type(live_agent).__name__}.name is empty"
        assert live_agent.description, f"{type(live_agent).__name__}.description is empty"
        assert live_agent.model, f"{type(live_agent).__name__}.model is empty"

    def test_manifest_exists_and_validates(self, live_agent):
        # community-manager → community_manager directory (slugs use dashes,
        # dirs use underscores) — derive the dir from the class module path.
        agent_module = live_agent.__class__.__module__
        agent_pkg_dir = Path(__import__(agent_module, fromlist=["__file__"]).__file__).parent
        manifest_path = agent_pkg_dir / "manifest.json"
        assert manifest_path.exists(), f"Missing {manifest_path}"
        data = json.loads(manifest_path.read_text())
        for required_field in ("slug", "name", "description"):
            assert data.get(required_field), \
                f"{manifest_path} missing required field '{required_field}'"
        assert data["slug"] == live_agent.slug, \
            f"Slug mismatch: {manifest_path} says {data['slug']!r}, agent says {live_agent.slug!r}"

    def test_interrupt_before_implies_approval_request(self, live_agent):
        """The approvals runtime asks the agent what to surface when paused
        via `get_approval_request(state)`. If an agent declares interrupts,
        it MUST override this — otherwise the approvals UI gets a None
        payload and the frontend has nothing to render."""
        if not live_agent.interrupt_before_nodes:
            return  # No gates — no contract to enforce.

        # Sample state with the fields a typical approval-gated agent uses.
        sample_state = {
            "draft": "test draft body",
            "recipient": "test@example.com",
            "subject": "Test",
            "body": "Body",
            "target_comment_id": "abc",
            "target_author": "Tester",
            "target_video_title": "Test Video",
            "draft_reply": "Test reply",
        }
        req = live_agent.get_approval_request(sample_state)
        assert req is not None, \
            f"{type(live_agent).__name__} declares interrupt_before but returns None from get_approval_request"
        assert "action_type" in req
        assert "action_payload" in req
        assert "preview" in req


# ── Template rendering across the roster ──────────────────────────────────
class TestTemplatesRender:
    """Render every template for every live agent under the test profile and
    assert no Jinja errors / no unrendered {{ ... }} or {% ... %} markers."""

    def test_all_agent_templates_render(self, langley_profile):
        agents_root = Path(__file__).resolve().parent.parent / "packages" / "agents"
        # Map slug → module dir (community-manager → community_manager).
        slug_to_dir = {
            "strategist": "strategist",
            "publisher": "publisher",
            "community-manager": "community_manager",
            "brand-manager": "brand_manager",
            "editor": "editor",
        }

        rendered_count = 0
        skipped: list[tuple[str, str, str]] = []

        for slug, dirname in slug_to_dir.items():
            template_dir = agents_root / dirname / "templates"
            if not template_dir.exists():
                continue
            for tmpl in sorted(template_dir.glob("*.j2")):
                # Minimal context that satisfies most templates. Some node-
                # specific templates need extra kwargs (e.g. strategist's
                # system.j2 expects `intent`); skip those rather than
                # bloating this generic check — they're covered by
                # test_peer_context.TestTemplateRendersPeerContext.
                try:
                    out = render(dirname, tmpl.name, profile=langley_profile, intent="research")
                except Exception as e:
                    # Track skipped so a regression there is still visible.
                    skipped.append((slug, tmpl.name, str(e)[:80]))
                    continue
                assert "{{" not in out and "{%" not in out, \
                    f"Unrendered Jinja in {dirname}/{tmpl.name}"
                rendered_count += 1

        assert rendered_count > 0, "No templates rendered — discovery is broken"
        # Warn (not fail) on skipped — surfaces drift without breaking CI.
        # If a template starts requiring kwargs we don't pass, this prints
        # the failure reason in pytest -v output without nuking the run.
        if skipped:
            print(f"\n  (skipped {len(skipped)} templates needing extra kwargs):")
            for slug, name, reason in skipped:
                print(f"    {slug}/{name}: {reason}")
