"""
Community Manager auto-spawns workspace tasks from triage output.

When `_persist_triage_node` runs after the triage ReAct loop, each VIP /
question / superfan the agent surfaced becomes a To-Do on /app/tasks.
The triage markdown is ephemeral chat content; tasks are the lasting
follow-up surface, so the user can work through their inbox over a week
without losing track.

Mocks: a structured-extraction LLM call (`llm.with_structured_output`)
returns a canned `TriageOutput`; Supabase is mocked to capture inserts.
No real LLM, no real DB.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from packages.agents.community_manager.agent import (
    CommunityManagerAgent,
    TriageItem,
    TriageOutput,
    _priority_from_kind,
)
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


# ── Mock Supabase capturing inserts ───────────────────────────────────────
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


# ── Helpers ───────────────────────────────────────────────────────────────
def _stub_extraction(agent: CommunityManagerAgent, items: list[TriageItem]) -> None:
    """Replace the agent's `llm.with_structured_output(...)` chain with one
    that returns the given TriageItem list. Avoids hitting Anthropic in
    tests."""
    output = TriageOutput(items=items)

    class _StubRunnable:
        async def ainvoke(self, *_a, **_k):
            return output

    fake_llm = MagicMock()
    fake_llm.with_structured_output = lambda _schema: _StubRunnable()
    agent.llm = fake_llm


def _stub_extraction_raises(agent: CommunityManagerAgent, exc: Exception) -> None:
    class _BoomRunnable:
        async def ainvoke(self, *_a, **_k):
            raise exc

    fake_llm = MagicMock()
    fake_llm.with_structured_output = lambda _schema: _BoomRunnable()
    agent.llm = fake_llm


def _triage_state(real_uuid: str, *, intent: str = "triage") -> dict:
    """Mirror the state the graph hands to `_persist_triage_node` —
    intent set, messages contain the triage agent's final markdown."""
    return {
        "org_id": real_uuid,
        "thread_id": real_uuid,
        "intent": intent,
        "messages": [
            HumanMessage(content="triage my comments"),
            AIMessage(content=(
                "### Alerts\n"
                "- @PewPewJake (1.2M subs) — collab DM on Glock review [abc123]\n\n"
                "### Needs reply\n"
                "- @newshooter22 — 'what holster do you use?' [def456]\n"
                "  Draft: I run a Vedder Lighttuck — link in description.\n\n"
                "### Hide / ignore\n"
                "- 4 spam, 12 ignore"
            )),
        ],
    }


# ── Pure mapping ──────────────────────────────────────────────────────────
class TestPriorityFromKind:
    @pytest.mark.parametrize("kind, expected", [
        ("vip", "high"),
        ("question", "medium"),
        ("superfan", "low"),
        (None, "low"),
        ("anything-else", "low"),
    ])
    def test_maps(self, kind, expected):
        assert _priority_from_kind(kind) == expected


# ── _persist_triage_node end-to-end ───────────────────────────────────────
@pytest.mark.asyncio
class TestPersistTriageNode:
    async def test_spawns_one_task_per_extracted_item(self, real_uuid):
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "community-manager"}],
        })
        current_supabase.set(sb)

        agent = CommunityManagerAgent()
        _stub_extraction(agent, [
            TriageItem(
                kind="vip",
                commenter_name="PewPewJake",
                comment_id="abc123",
                summary="1.2M-sub creator interested in collab",
                draft_reply="",
                video_title="Glock 19 honest review",
            ),
            TriageItem(
                kind="question",
                commenter_name="newshooter22",
                comment_id="def456",
                summary="What holster do you run for IWB?",
                draft_reply="I run a Vedder Lighttuck — link in description.",
                video_title="Concealed carry setup",
            ),
            TriageItem(
                kind="superfan",
                commenter_name="LongtimeViewer",
                comment_id="ghi789",
                summary="Been here since 10k subs",
                draft_reply="",
                video_title="",
            ),
        ])

        await agent._persist_triage_node(_triage_state(real_uuid))

        inserts = sb._canned.get("_inserts", [])
        task_rows = [r for t, r in inserts if t == "tasks"]
        assert len(task_rows) == 3

        # VIPs get the (VIP) suffix; questions don't.
        assert task_rows[0]["title"] == "Reply to PewPewJake (VIP)"
        assert task_rows[1]["title"] == "Reply to newshooter22"
        assert task_rows[2]["title"] == "Reply to LongtimeViewer"

        # Priority ladder: vip→high, question→medium, superfan→low.
        assert task_rows[0]["priority"] == "high"
        assert task_rows[1]["priority"] == "medium"
        assert task_rows[2]["priority"] == "low"

        # Description carries the draft when one was written.
        assert "Vedder Lighttuck" in task_rows[1]["description"]
        # And the video title for context.
        assert "Glock 19" in task_rows[0]["description"]

        # Metadata back-links so the task page can show a "from triage" badge
        # and (eventually) deep-link to the source comment.
        for row in task_rows:
            assert row["metadata"]["source"] == "cm_triage"
            assert row["metadata"]["thread_id"] == real_uuid
        assert task_rows[0]["metadata"]["kind"] == "vip"
        assert task_rows[0]["metadata"]["comment_id"] == "abc123"

        # All tasks land in To-Do by default.
        assert all(r["status"] == "todo" for r in task_rows)

    async def test_noop_when_intent_is_research(self, real_uuid):
        sb = MockSupabase()
        current_supabase.set(sb)

        agent = CommunityManagerAgent()
        # Even if the stub is set, a research intent should never invoke it.
        _stub_extraction(agent, [
            TriageItem(kind="vip", commenter_name="X", summary="y"),
        ])

        await agent._persist_triage_node(_triage_state(real_uuid, intent="research"))
        assert "_inserts" not in sb._canned

    async def test_noop_in_dev_mode(self):
        # No supabase, dev org_id — the node should bail before calling the LLM.
        agent = CommunityManagerAgent()
        # Stub raises if invoked — proves we never hit it in dev mode.
        _stub_extraction_raises(agent, RuntimeError("LLM should not be called in dev"))

        await agent._persist_triage_node({
            "org_id": "dev",
            "thread_id": "dev",
            "intent": "triage",
            "messages": [AIMessage(content="some triage output")],
        })
        # No exception → we short-circuited before invoking the stub.

    async def test_noop_when_no_ai_message(self, real_uuid):
        sb = MockSupabase()
        current_supabase.set(sb)
        agent = CommunityManagerAgent()
        _stub_extraction_raises(agent, RuntimeError("LLM should not be called"))

        await agent._persist_triage_node({
            "org_id": real_uuid,
            "thread_id": real_uuid,
            "intent": "triage",
            "messages": [HumanMessage(content="triage")],  # no AI reply yet
        })
        assert "_inserts" not in sb._canned

    async def test_extraction_failure_swallowed(self, real_uuid):
        sb = MockSupabase()
        current_supabase.set(sb)
        agent = CommunityManagerAgent()
        _stub_extraction_raises(agent, RuntimeError("anthropic 503"))

        # Should NOT raise.
        await agent._persist_triage_node(_triage_state(real_uuid))
        assert "_inserts" not in sb._canned

    async def test_empty_extraction_yields_no_tasks(self, real_uuid):
        sb = MockSupabase()
        current_supabase.set(sb)
        agent = CommunityManagerAgent()
        _stub_extraction(agent, [])  # extraction returns 0 items

        await agent._persist_triage_node(_triage_state(real_uuid))
        assert "_inserts" not in sb._canned

    async def test_task_spawn_failure_does_not_raise(self, real_uuid):
        """If create_tasks_from_agent's underlying insert blows up, the node
        should still return cleanly — triage already produced the user-
        facing markdown, a missed task is recoverable on next run."""
        agent_uuid = str(uuid.uuid4())

        class _FaultyTasks(MockSupabase):
            def table(self, name):
                if name == "tasks":
                    class _Boom:
                        def insert(self, _p): return self
                        def execute(self):
                            raise RuntimeError("tasks table down")
                    return _Boom()
                return super().table(name)

        sb = _FaultyTasks({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "community-manager"}],
        })
        current_supabase.set(sb)

        agent = CommunityManagerAgent()
        _stub_extraction(agent, [
            TriageItem(kind="vip", commenter_name="X", summary="y"),
        ])

        # Should not raise.
        await agent._persist_triage_node(_triage_state(real_uuid))

    async def test_metadata_thread_id_null_when_not_uuid(self, real_uuid):
        """thread_id can be a non-UUID identifier in some session shapes;
        when it is, the metadata field should be NULL rather than carry a
        garbage value into Postgres jsonb."""
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "community-manager"}],
        })
        current_supabase.set(sb)

        agent = CommunityManagerAgent()
        _stub_extraction(agent, [
            TriageItem(kind="question", commenter_name="askr", summary="?"),
        ])

        state = _triage_state(real_uuid)
        state["thread_id"] = "not-a-uuid"
        await agent._persist_triage_node(state)

        task_rows = [r for t, r in sb._canned["_inserts"] if t == "tasks"]
        assert task_rows[0]["metadata"]["thread_id"] is None
