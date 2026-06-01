"""
monday.com task delegation + progress logging helpers
(`packages/agents/core/monday_tasks.py`).

These verify the best-effort contract: the helpers no-op gracefully (return
None / empty list) when no monday.com connection exists for an org, when the
org is the dev fallback, or when the lookup/HTTP path explodes. The connected
path is exercised with monkeypatched monday GraphQL calls so no network hits.

No live monday.com or Postgres — a hand-rolled MockSupabase serves the
`integrations` row and the GraphQL client functions are monkeypatched.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from packages.agents.core import monday_tasks
from packages.integrations.context import current_supabase


@pytest.fixture(autouse=True)
def _reset_contextvars():
    current_supabase.set(None)
    yield
    current_supabase.set(None)


@pytest.fixture
def real_uuid() -> str:
    return str(uuid.uuid4())


# ── MockSupabase — serves a canned `integrations` row ─────────────────────
class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    def __init__(self, table_name: str, canned: dict):
        self._table = table_name
        self._canned = canned

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def execute(self):
        return _MockResult(self._canned.get(self._table, []))


class MockSupabase:
    def __init__(self, canned: dict | None = None):
        self._canned = canned or {}

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._canned)


def _connected_supabase(org_id: str, token: str = "monday_tok_abc") -> MockSupabase:
    """A MockSupabase with an active monday.com integration row for the org."""
    return MockSupabase({
        "integrations": [{
            "org_id": org_id,
            "provider": "monday",
            "status": "active",
            "access_token": token,
        }],
    })


# ── _resolve_access_token ──────────────────────────────────────────────────
class TestResolveAccessToken:
    def test_returns_token_when_connected(self, real_uuid):
        sb = _connected_supabase(real_uuid)
        assert monday_tasks._resolve_access_token(real_uuid, sb) == "monday_tok_abc"

    def test_none_when_no_supabase(self, real_uuid):
        assert monday_tasks._resolve_access_token(real_uuid, None) is None

    def test_none_when_dev_org(self):
        sb = _connected_supabase("dev")
        assert monday_tasks._resolve_access_token("dev", sb) is None

    def test_none_when_no_connection(self, real_uuid):
        sb = MockSupabase({"integrations": []})
        assert monday_tasks._resolve_access_token(real_uuid, sb) is None

    def test_none_when_connection_errored(self, real_uuid):
        sb = MockSupabase({"integrations": [{
            "org_id": real_uuid, "provider": "monday",
            "status": "error", "access_token": "stale",
        }]})
        assert monday_tasks._resolve_access_token(real_uuid, sb) is None

    def test_none_when_lookup_raises(self, real_uuid):
        class _Boom(MockSupabase):
            def table(self, name):
                raise RuntimeError("DB down")
        assert monday_tasks._resolve_access_token(real_uuid, _Boom()) is None


# ── monday_create_item ─────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestMondayCreateItem:
    async def test_noop_no_connection(self, real_uuid):
        current_supabase.set(MockSupabase({"integrations": []}))
        result = await monday_tasks.monday_create_item(
            real_uuid, board_id="123", item_name="Follow up with Magpul",
        )
        assert result is None

    async def test_noop_dev_mode(self):
        # No supabase set at all.
        result = await monday_tasks.monday_create_item(
            "dev", board_id="123", item_name="x",
        )
        assert result is None

    async def test_noop_blank_inputs(self, real_uuid):
        current_supabase.set(_connected_supabase(real_uuid))
        assert await monday_tasks.monday_create_item(
            real_uuid, board_id="", item_name="x") is None
        assert await monday_tasks.monday_create_item(
            real_uuid, board_id="123", item_name="  ") is None

    async def test_creates_item_when_connected(self, real_uuid, monkeypatch):
        current_supabase.set(_connected_supabase(real_uuid))

        async def fake_create_item(token, *, board_id, item_name, column_values=None):
            assert token == "monday_tok_abc"
            assert board_id == "123"
            return {"id": "item_42", "name": item_name}

        monkeypatch.setattr(monday_tasks.monday_client, "create_item", fake_create_item)
        result = await monday_tasks.monday_create_item(
            real_uuid, board_id="123", item_name="Follow up with Magpul",
        )
        assert result == "item_42"

    async def test_group_id_uses_graphql(self, real_uuid, monkeypatch):
        current_supabase.set(_connected_supabase(real_uuid))
        captured: dict[str, Any] = {}

        async def fake_graphql(token, query, variables=None):
            captured["variables"] = variables
            return {"create_item": {"id": "item_99"}}

        monkeypatch.setattr(monday_tasks.monday_client, "graphql", fake_graphql)
        result = await monday_tasks.monday_create_item(
            real_uuid, board_id="123", item_name="x", group_id="grp_1",
        )
        assert result == "item_99"
        assert captured["variables"]["group"] == "grp_1"

    async def test_http_error_does_not_raise(self, real_uuid, monkeypatch):
        current_supabase.set(_connected_supabase(real_uuid))

        async def boom(*a, **k):
            raise RuntimeError("monday.com GraphQL HTTP 500")

        monkeypatch.setattr(monday_tasks.monday_client, "create_item", boom)
        result = await monday_tasks.monday_create_item(
            real_uuid, board_id="123", item_name="x")
        assert result is None


# ── monday_log_progress ────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestMondayLogProgress:
    async def test_noop_no_connection(self, real_uuid):
        current_supabase.set(MockSupabase({"integrations": []}))
        result = await monday_tasks.monday_log_progress(
            real_uuid, board_id="123", item_name="Pitch update", note="Sent.",
        )
        assert result is None

    async def test_noop_dev_mode(self):
        result = await monday_tasks.monday_log_progress(
            "dev", board_id="123", item_name="x", note="y")
        assert result is None

    async def test_logs_progress_and_posts_update(self, real_uuid, monkeypatch):
        current_supabase.set(_connected_supabase(real_uuid))
        update_posted: dict[str, Any] = {}

        async def fake_create_item(token, *, board_id, item_name, column_values=None):
            return {"id": "item_7"}

        async def fake_graphql(token, query, variables=None):
            update_posted["variables"] = variables
            return {"create_update": {"id": "upd_1"}}

        monkeypatch.setattr(monday_tasks.monday_client, "create_item", fake_create_item)
        monkeypatch.setattr(monday_tasks.monday_client, "graphql", fake_graphql)

        result = await monday_tasks.monday_log_progress(
            real_uuid, board_id="123", item_name="Magpul",
            note="Pitched — awaiting reply",
        )
        assert result == "item_7"
        assert update_posted["variables"]["item"] == "item_7"
        assert update_posted["variables"]["body"] == "Pitched — awaiting reply"

    async def test_returns_item_even_if_update_fails(self, real_uuid, monkeypatch):
        current_supabase.set(_connected_supabase(real_uuid))

        async def fake_create_item(token, *, board_id, item_name, column_values=None):
            return {"id": "item_8"}

        async def boom_graphql(*a, **k):
            raise RuntimeError("update failed")

        monkeypatch.setattr(monday_tasks.monday_client, "create_item", fake_create_item)
        monkeypatch.setattr(monday_tasks.monday_client, "graphql", boom_graphql)

        result = await monday_tasks.monday_log_progress(
            real_uuid, board_id="123", item_name="Magpul", note="note",
        )
        assert result == "item_8"

    async def test_create_error_does_not_raise(self, real_uuid, monkeypatch):
        current_supabase.set(_connected_supabase(real_uuid))

        async def boom(*a, **k):
            raise RuntimeError("nope")

        monkeypatch.setattr(monday_tasks.monday_client, "create_item", boom)
        result = await monday_tasks.monday_log_progress(
            real_uuid, board_id="123", item_name="x", note="y")
        assert result is None


# ── monday_list_boards ──────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestMondayListBoards:
    async def test_empty_no_connection(self, real_uuid):
        current_supabase.set(MockSupabase({"integrations": []}))
        assert await monday_tasks.monday_list_boards(real_uuid) == []

    async def test_empty_dev_mode(self):
        assert await monday_tasks.monday_list_boards("dev") == []

    async def test_empty_no_supabase(self, real_uuid):
        assert await monday_tasks.monday_list_boards(real_uuid) == []

    async def test_returns_boards_when_connected(self, real_uuid, monkeypatch):
        current_supabase.set(_connected_supabase(real_uuid))

        async def fake_list_boards(token, limit=25):
            assert token == "monday_tok_abc"
            return [{"id": "1", "name": "Sponsors", "state": "active"}]

        monkeypatch.setattr(monday_tasks.monday_client, "list_boards", fake_list_boards)
        boards = await monday_tasks.monday_list_boards(real_uuid)
        assert len(boards) == 1
        assert boards[0]["name"] == "Sponsors"

    async def test_http_error_returns_empty(self, real_uuid, monkeypatch):
        current_supabase.set(_connected_supabase(real_uuid))

        async def boom(*a, **k):
            raise RuntimeError("monday.com GraphQL HTTP 401")

        monkeypatch.setattr(monday_tasks.monday_client, "list_boards", boom)
        assert await monday_tasks.monday_list_boards(real_uuid) == []
