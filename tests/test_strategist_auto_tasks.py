"""
Strategist auto-spawns tasks from briefs — `_persist_brief_node` writes
both the `strategist_briefs` row AND one `tasks` row per ranked idea.

Tests use a mock Supabase to capture inserts; no real DB or LLM. Two
classes split coverage:

  - `TestPriorityMapping` — pure mapping, parametrized
  - `TestPersistBriefSpawnsTasks` — exercises `_persist_brief_node` end
    to end, asserts both tables get the right rows
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from packages.agents.core.tasks import (
    _resolve_agent_id,
    create_task_from_agent,
    create_tasks_from_agent,
)
from packages.agents.strategist.agent import StrategistAgent, _priority_from_confidence
from packages.integrations.context import (
    current_org_id,
    current_supabase,
    current_user_id,
)


@pytest.fixture(autouse=True)
def _reset_contextvars():
    current_org_id.set(None)
    current_user_id.set(None)
    current_supabase.set(None)
    yield


@pytest.fixture
def real_uuid() -> str:
    return str(uuid.uuid4())


# ── MockSupabase capturing inserts per table ──────────────────────────────
class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    def __init__(self, table_name: str, canned: dict):
        self._table = table_name
        self._canned = canned
        self._inserted: dict | None = None

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def insert(self, payload: dict):
        self._inserted = payload
        with_id = {"id": str(uuid.uuid4()), **payload}
        self._canned.setdefault(self._table, []).append(with_id)
        self._canned.setdefault("_inserts", []).append((self._table, with_id))
        return self

    def execute(self):
        if self._inserted is not None:
            return _MockResult([self._canned[self._table][-1]])
        return _MockResult(self._canned.get(self._table, []))


class MockSupabase:
    def __init__(self, canned: dict | None = None):
        self._canned = canned or {}

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._canned)


# ── Pure mapping ──────────────────────────────────────────────────────────
class TestPriorityMapping:
    @pytest.mark.parametrize("confidence, expected", [
        ("high", "high"),
        ("medium", "medium"),
        ("low", "low"),
        (None, "medium"),
        ("anything-else", "medium"),
    ])
    def test_maps(self, confidence, expected):
        assert _priority_from_confidence(confidence) == expected


# ── create_task_from_agent ────────────────────────────────────────────────
@pytest.mark.asyncio
class TestCreateTaskFromAgent:
    async def test_inserts_row_with_resolved_agent_id(self, real_uuid):
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            # agents row keyed on (org_id, slug). _resolve_agent_id finds it.
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })
        current_supabase.set(sb)

        new_id = await create_task_from_agent(
            org_id=real_uuid,
            agent_slug="strategist",
            title="Plan next video",
            description="Hook: …",
            priority="high",
            metadata={"source": "test"},
        )
        assert new_id is not None
        inserts = sb._canned["_inserts"]
        # First insert in `agents` is the SELECT; only `tasks` should appear.
        task_inserts = [(t, r) for t, r in inserts if t == "tasks"]
        assert len(task_inserts) == 1
        _, row = task_inserts[0]
        assert row["title"] == "Plan next video"
        assert row["agent_id"] == agent_uuid
        assert row["priority"] == "high"
        assert row["status"] == "todo"
        assert row["metadata"] == {"source": "test"}

    async def test_falls_back_to_null_agent_id_when_slug_unknown(self, real_uuid):
        # agents table empty → _resolve_agent_id returns None
        sb = MockSupabase()
        current_supabase.set(sb)

        new_id = await create_task_from_agent(
            org_id=real_uuid,
            agent_slug="unknown-slug",
            title="Standalone task",
        )
        assert new_id is not None
        task_inserts = [(t, r) for t, r in sb._canned["_inserts"] if t == "tasks"]
        assert task_inserts[0][1]["agent_id"] is None

    async def test_noop_in_dev_mode(self):
        # No supabase, dev org_id — pure no-op.
        result = await create_task_from_agent(
            org_id="dev",
            agent_slug="strategist",
            title="x",
        )
        assert result is None

    async def test_noop_when_title_blank(self, real_uuid):
        sb = MockSupabase()
        current_supabase.set(sb)
        result = await create_task_from_agent(
            org_id=real_uuid,
            agent_slug="strategist",
            title="   ",
        )
        assert result is None
        assert "_inserts" not in sb._canned

    async def test_db_error_does_not_raise(self, real_uuid):
        class _Faulty(MockSupabase):
            def table(self, name):
                # `agents` lookup must succeed (returns empty); `tasks` insert
                # raises so we exercise the swallow-and-return-None path.
                if name == "tasks":
                    class _BoomQuery:
                        def insert(self, _payload): return self
                        def execute(self):
                            raise RuntimeError("db down")
                    return _BoomQuery()
                return super().table(name)

        current_supabase.set(_Faulty())
        result = await create_task_from_agent(
            org_id=real_uuid,
            agent_slug="strategist",
            title="x",
        )
        assert result is None  # swallowed, didn't raise


# ── create_tasks_from_agent (bulk) ────────────────────────────────────────
@pytest.mark.asyncio
class TestBulkCreate:
    async def test_returns_ids_for_successful_inserts(self, real_uuid):
        sb = MockSupabase()
        current_supabase.set(sb)

        items = [
            {"title": "A", "priority": "high"},
            {"title": "B", "priority": "low"},
            {"title": "  ", "priority": "low"},  # blank → skipped
            {"title": "C"},
        ]
        ids = await create_tasks_from_agent(
            org_id=real_uuid,
            agent_slug="strategist",
            items=items,
        )
        # Three real titles → three ids.
        assert len(ids) == 3
        # Three task inserts captured.
        task_inserts = [t for t, _ in sb._canned["_inserts"] if t == "tasks"]
        assert len(task_inserts) == 3


# ── End-to-end: persist_brief spawns brief AND task rows ──────────────────
@pytest.mark.asyncio
class TestPersistBriefSpawnsTasks:
    async def test_spawns_one_task_per_idea(self, real_uuid):
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })
        current_supabase.set(sb)

        agent = StrategistAgent()
        state = {
            "org_id": real_uuid,
            "thread_id": real_uuid,
            "brief": {
                "headline": "Lean into 2A education this week",
                "ideas": [
                    {
                        "title": "The argument leftists can't refute",
                        "hook": "Every conservative loses 2A debates because…",
                        "why_now": "Heritage report — high urgency",
                        "confidence": "high",
                        "rationale": "matches recent uploads",
                        "citations": [],
                    },
                    {
                        "title": "Every gun owner's 2026 checklist",
                        "hook": "2026 changed the rules…",
                        "why_now": "SAF report — rising",
                        "confidence": "medium",
                        "rationale": "practical content drives comments",
                        "citations": [],
                    },
                    {
                        "title": "",  # empty — skipped
                        "hook": "",
                        "why_now": "",
                        "confidence": "low",
                        "rationale": "",
                        "citations": [],
                    },
                ],
            },
        }
        await agent._persist_brief_node(state)

        inserts = sb._canned.get("_inserts", [])
        # Exactly one strategist_briefs row + two task rows (third idea blank-skipped).
        brief_rows = [r for t, r in inserts if t == "strategist_briefs"]
        task_rows = [r for t, r in inserts if t == "tasks"]
        assert len(brief_rows) == 1
        assert len(task_rows) == 2

        # Tasks point at the brief via metadata.
        assert all(r["metadata"]["source"] == "strategist_brief" for r in task_rows)
        assert all(r["metadata"]["brief_id"] == brief_rows[0]["id"] for r in task_rows)
        assert task_rows[0]["metadata"]["idea_index"] == 0
        assert task_rows[1]["metadata"]["idea_index"] == 1

        # Confidence drives priority.
        assert task_rows[0]["priority"] == "high"
        assert task_rows[1]["priority"] == "medium"

        # Description carries hook + why-now context for the user.
        assert "Hook: Every conservative" in task_rows[0]["description"]
        assert "Why now:" in task_rows[0]["description"]

        # All tasks land in the To-Do column by default.
        assert all(r["status"] == "todo" for r in task_rows)

    async def test_noop_in_dev_mode(self):
        agent = StrategistAgent()
        # No supabase, dev org_id.
        await agent._persist_brief_node({
            "org_id": "dev",
            "thread_id": "dev",
            "brief": {"headline": "x", "ideas": [{"title": "y", "confidence": "high"}]},
        })
        # No exception, no DB calls. Test passes if we got here.

    async def test_brief_persists_even_when_task_spawning_breaks(self, real_uuid):
        """If the bulk task insert hits an error, the brief itself should
        still have been written — they're independent best-effort steps."""
        agent_uuid = str(uuid.uuid4())

        class _PartialFaulty(MockSupabase):
            def table(self, name):
                if name == "tasks":
                    class _BoomQuery:
                        def insert(self, _p): return self
                        def execute(self):
                            raise RuntimeError("tasks down")
                    return _BoomQuery()
                return super().table(name)

        sb = _PartialFaulty({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })
        current_supabase.set(sb)

        agent = StrategistAgent()
        await agent._persist_brief_node({
            "org_id": real_uuid,
            "thread_id": real_uuid,
            "brief": {
                "headline": "x",
                "ideas": [{"title": "y", "hook": "z", "why_now": "w",
                           "confidence": "high", "rationale": "r", "citations": []}],
            },
        })

        brief_inserts = [r for t, r in sb._canned.get("_inserts", []) if t == "strategist_briefs"]
        assert len(brief_inserts) == 1


# ── _resolve_agent_id ─────────────────────────────────────────────────────
class TestResolveAgentId:
    def test_finds_existing_agent(self, real_uuid):
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })
        assert _resolve_agent_id(sb, real_uuid, "strategist") == agent_uuid

    def test_returns_none_for_unknown(self, real_uuid):
        sb = MockSupabase()
        assert _resolve_agent_id(sb, real_uuid, "no-such-slug") is None

    def test_returns_none_on_db_error(self, real_uuid):
        class _Faulty(MockSupabase):
            def table(self, name):
                raise RuntimeError("nope")

        assert _resolve_agent_id(_Faulty(), real_uuid, "strategist") is None
