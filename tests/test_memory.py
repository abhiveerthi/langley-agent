"""
Long-term agent memory — embedding gating, write/recall no-op paths, and the
BaseAgent load_memory node hydrating state.

Hermetic by design (mirrors tests/test_peer_context.py):
  - No network: embed_text returns None without OPENAI_API_KEY, so nothing
    here ever issues an HTTP request.
  - No Postgres: writes/recalls no-op without a configured Supabase / a real
    org UUID.
"""
from __future__ import annotations

import pytest

from packages.agents.core.memory import (
    _is_real_uuid,
    embed_text,
    recall_memories,
    write_memory,
)
from packages.integrations.context import current_supabase


# ── _is_real_uuid edge cases ──────────────────────────────────────────────
class TestIsRealUuid:
    @pytest.mark.parametrize("value, expected", [
        ("dev", False),
        ("", False),
        (None, False),
        ("not-a-uuid", False),
        ("123e4567-e89b-12d3-a456-426614174000", True),
    ])
    def test_classifies_correctly(self, value, expected):
        assert _is_real_uuid(value) is expected


# ── embed_text without an API key ─────────────────────────────────────────
class TestEmbedText:
    async def test_returns_none_without_key(self, monkeypatch):
        """No OPENAI_API_KEY → None, and no network call is attempted."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("MEMORY_EMBED_PROVIDER", "openai")
        assert await embed_text("anything") is None

    async def test_returns_none_on_blank_text(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        assert await embed_text("") is None
        assert await embed_text("   ") is None

    async def test_unknown_provider_returns_none(self, monkeypatch):
        """An unconfigured provider degrades to None rather than guessing."""
        monkeypatch.setenv("MEMORY_EMBED_PROVIDER", "nonexistent-backend")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        assert await embed_text("anything") is None


# ── write_memory no-op paths ──────────────────────────────────────────────
class TestWriteMemoryNoops:
    async def test_no_supabase(self, real_uuid, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        current_supabase.set(None)
        # Should complete cleanly with no exception, returns None.
        assert await write_memory(real_uuid, "strategist", real_uuid, "hi") is None

    async def test_non_uuid_org(self, mock_supabase_factory, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        sb = mock_supabase_factory()
        current_supabase.set(sb)
        await write_memory("dev", "strategist", None, "hi")
        # Nothing inserted for a dev org.
        assert not sb._canned.get("_inserts")

    async def test_blank_content(self, real_uuid, mock_supabase_factory, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        sb = mock_supabase_factory()
        current_supabase.set(sb)
        await write_memory(real_uuid, "strategist", real_uuid, "   ")
        assert not sb._canned.get("_inserts")

    async def test_no_embedding_backend_skips_insert(
        self, real_uuid, mock_supabase_factory, monkeypatch
    ):
        """Supabase + real org, but no embedding backend → embed_text is None
        so nothing is written (we never insert a row with a null embedding)."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        sb = mock_supabase_factory()
        current_supabase.set(sb)
        await write_memory(real_uuid, "strategist", real_uuid, "real content")
        assert not sb._canned.get("_inserts")


# ── recall_memories no-op paths ───────────────────────────────────────────
class TestRecallMemoriesNoops:
    async def test_no_supabase(self, real_uuid, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        current_supabase.set(None)
        assert await recall_memories(real_uuid, "strategist", "what did we plan") == []

    async def test_non_uuid_org(self, mock_supabase_factory, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        current_supabase.set(mock_supabase_factory())
        assert await recall_memories("dev", "strategist", "query") == []

    async def test_blank_query(self, real_uuid, mock_supabase_factory, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
        current_supabase.set(mock_supabase_factory())
        assert await recall_memories(real_uuid, "strategist", "  ") == []

    async def test_no_embedding_backend_returns_empty(
        self, real_uuid, mock_supabase_factory, monkeypatch
    ):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        current_supabase.set(mock_supabase_factory())
        assert await recall_memories(real_uuid, "strategist", "query") == []


# ── BaseAgent load_memory node ────────────────────────────────────────────
class TestLoadMemoryNode:
    def _stub_agent(self, *, enabled: bool):
        from packages.agents.core.base import BaseAgent

        class _StubAgent(BaseAgent):
            slug = "stub"
            name = "Stub"
            memory_enabled = enabled

            def build_graph(self):
                from langgraph.graph import StateGraph, END, START
                g = StateGraph(dict)
                g.add_node("a", lambda _s: {})
                g.add_edge(START, "a")
                g.add_edge("a", END)
                return g

        return _StubAgent()

    async def test_disabled_agent_sets_empty_memories(self, real_uuid):
        agent = self._stub_agent(enabled=False)
        state = {"org_id": real_uuid, "metadata": {"existing": "kept"}, "messages": []}
        update = await agent._load_memory_node(state)
        assert update["metadata"]["memories"] == []
        # Pre-existing metadata must not be clobbered.
        assert update["metadata"]["existing"] == "kept"

    async def test_enabled_agent_noop_without_backend(self, real_uuid, monkeypatch):
        """Memory enabled, but no embedding backend → empty list, state usable."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        current_supabase.set(None)
        agent = self._stub_agent(enabled=True)
        state = {
            "org_id": real_uuid,
            "metadata": {"existing": "kept"},
            "messages": [{"role": "user", "content": "what should I make next?"}],
        }
        update = await agent._load_memory_node(state)
        assert update["metadata"]["memories"] == []
        assert update["metadata"]["existing"] == "kept"

    async def test_persist_turn_memory_noop_when_disabled(self, real_uuid):
        agent = self._stub_agent(enabled=False)
        # No exception, returns None — nothing to persist when memory is off.
        assert await agent._persist_turn_memory(
            {"org_id": real_uuid, "thread_id": real_uuid, "messages": []}
        ) is None

    async def test_persist_turn_memory_noop_without_supabase(self, real_uuid, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        current_supabase.set(None)
        agent = self._stub_agent(enabled=True)
        state = {
            "org_id": real_uuid,
            "thread_id": real_uuid,
            "messages": [
                {"role": "user", "content": "plan my week"},
                {"role": "assistant", "content": "Here's the plan."},
            ],
        }
        # Best-effort: completes cleanly even though there's nowhere to write.
        assert await agent._persist_turn_memory(state) is None


# ── Template renders the memory partial ───────────────────────────────────
class TestMemoryTemplate:
    def test_strategist_system_renders_memories(self, langley_profile):
        from packages.agents.core.templates import render
        memories = [
            {"content": "MEMORY_RECALL_MARKER — creator prefers shorter videos"},
        ]
        out = render(
            "strategist", "system.j2", profile=langley_profile,
            intent="research", peer_context={}, memories=memories,
        )
        assert "MEMORY_RECALL_MARKER" in out

    def test_omits_block_when_memories_absent(self, langley_profile):
        from packages.agents.core.templates import render
        # Empty list (dev-mode shape).
        out = render(
            "strategist", "system.j2", profile=langley_profile,
            intent="research", peer_context={}, memories=[],
        )
        assert "What you remember about working with this creator" not in out
        # Kwarg omitted entirely — partial guards on `memories is defined`.
        out2 = render(
            "strategist", "system.j2", profile=langley_profile,
            intent="research", peer_context={},
        )
        assert "What you remember about working with this creator" not in out2
