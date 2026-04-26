"""
Per-run structured outputs — `BaseAgent.get_structured_outputs(state,
visited_nodes)` and the orchestrator's `structured_output` SSE event.

The contract: any agent that produces a typed payload alongside the chat
text overrides the method to surface it. The orchestrator emits one
event per (kind, data) entry after astream finishes for a run, gated on
`visited_nodes` so stale state from earlier turns doesn't re-render the
same card on every follow-up.
"""
from __future__ import annotations

import json

import pytest

from packages.agents.brand_manager.agent import BrandManagerAgent
from packages.agents.strategist.agent import StrategistAgent


# ── Per-agent contract ───────────────────────────────────────────────────
class TestStrategistStructuredOutputs:
    def test_brief_emitted_when_compose_brief_visited(self):
        """Happy path: compose_brief actually ran this turn AND state has a
        brief — emit it under the `brief` kind."""
        agent = StrategistAgent()
        state = {"brief": {"headline": "test", "ideas": []}}
        out = agent.get_structured_outputs(
            state,
            ["load_profile", "classify_intent", "agent", "tools",
             "compose_brief", "persist_brief", "respond"],
        )
        assert out == {"brief": {"headline": "test", "ideas": []}}

    def test_brief_NOT_emitted_when_compose_brief_did_not_run(self):
        """Stale-state guard: brief field still on state (LangGraph
        checkpointer persists across turns) but compose_brief didn't run
        this turn — don't re-emit. Otherwise every follow-up question
        would re-show the same brief card."""
        agent = StrategistAgent()
        state = {"brief": {"headline": "stale from last turn", "ideas": []}}
        # Research / script_outline path doesn't run compose_brief.
        out = agent.get_structured_outputs(
            state,
            ["load_profile", "classify_intent", "agent", "respond"],
        )
        assert out == {}

    def test_brief_NOT_emitted_when_state_lacks_brief(self):
        agent = StrategistAgent()
        out = agent.get_structured_outputs({}, ["compose_brief"])
        assert out == {}

    def test_brief_NOT_emitted_when_brief_is_empty_dict(self):
        """Defensive: a `brief` key with an empty/falsy value shouldn't
        produce a phantom event."""
        agent = StrategistAgent()
        out = agent.get_structured_outputs({"brief": None}, ["compose_brief"])
        assert out == {}


class TestBrandManagerDefaultBehavior:
    """Brand Manager doesn't produce structured cards (today). The default
    BaseAgent implementation returns {} — verify the override either is
    absent or doesn't accidentally claim outputs that don't exist."""

    def test_returns_empty_for_any_state(self):
        agent = BrandManagerAgent()
        out = agent.get_structured_outputs(
            {"draft": "x", "recipient": "y@z.com"},
            ["classify_intent", "draft_pitch", "approval_gate"],
        )
        assert out == {}


# ── Orchestrator emits structured_output ──────────────────────────────────
@pytest.mark.asyncio
class TestOrchestratorEmission:
    """The orchestrator should call `agent.get_structured_outputs` after
    astream finishes and emit one SSE event per kind. Tested via a stub
    agent so we don't need a real LLM run."""

    async def test_emits_event_per_kind(self, monkeypatch):
        from app.services import graph_orchestrator as orch

        # Build a minimal stub agent that pretends compose_brief ran.
        class _StubAgent:
            slug = "stub-strategist"
            interrupt_before_nodes: list[str] = []

            def get_structured_outputs(self, state, visited):
                if "compose_brief" in visited:
                    return {"brief": {"headline": "stubbed", "ideas": [{"title": "A"}]}}
                return {}

            def get_approval_request(self, state):
                return None

        # Stub `app` returned by _compile_agent — no real graph, just an
        # async iterable for astream and a snapshot getter.
        class _StubSnapshot:
            def __init__(self):
                self.next = ()
                self.values = {"brief": {"headline": "stubbed", "ideas": [{"title": "A"}]}}

        class _StubApp:
            async def astream(self, input_data, config, stream_mode):
                # Pretend compose_brief ran by yielding it.
                yield {"compose_brief": {}}

            async def aget_state(self, config):
                return _StubSnapshot()

        async def fake_compile(_agent):
            return _StubApp()

        monkeypatch.setattr(orch, "_compile_agent", fake_compile)

        events: list[dict] = []
        async for sse in orch._stream_until_done_or_pause(
            await fake_compile(None),
            input_data={"messages": []},
            config={"configurable": {"thread_id": "t"}},
            agent=_StubAgent(),  # type: ignore[arg-type]
            org_id="dev",
            thread_id="t",
        ):
            line = sse.strip().removeprefix("data: ")
            events.append(json.loads(line))

        kinds = [e["type"] for e in events]
        assert "structured_output" in kinds, f"Expected structured_output in {kinds}"

        structured = next(e for e in events if e["type"] == "structured_output")
        assert structured["data"]["kind"] == "brief"
        assert structured["data"]["data"]["headline"] == "stubbed"
        # `done` should still fire after the structured outputs (graph wasn't paused).
        assert events[-1]["type"] == "done"

    async def test_no_event_when_agent_returns_empty(self, monkeypatch):
        """Default agents (Brand Manager, CM, Editor) should NOT trigger
        any structured_output events even though the orchestrator always
        calls the contract method."""
        from app.services import graph_orchestrator as orch

        class _Quiet:
            slug = "quiet"
            interrupt_before_nodes: list[str] = []
            def get_structured_outputs(self, state, visited): return {}
            def get_approval_request(self, state): return None

        class _StubSnapshot:
            next = ()
            values: dict = {}

        class _StubApp:
            async def astream(self, input_data, config, stream_mode):
                yield {"some_node": {}}

            async def aget_state(self, config):
                return _StubSnapshot()

        async def fake_compile(_a):
            return _StubApp()

        monkeypatch.setattr(orch, "_compile_agent", fake_compile)

        events: list[dict] = []
        async for sse in orch._stream_until_done_or_pause(
            await fake_compile(None),
            input_data={"messages": []},
            config={"configurable": {"thread_id": "t"}},
            agent=_Quiet(),  # type: ignore[arg-type]
            org_id="dev",
            thread_id="t",
        ):
            events.append(json.loads(sse.strip().removeprefix("data: ")))

        assert not any(e["type"] == "structured_output" for e in events)
        assert events[-1]["type"] == "done"
