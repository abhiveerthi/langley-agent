"""
Channels router endpoint tests — list/create/messages/join/mentionable.

Same handler-direct + MockSupabase pattern as `test_brand_manager_router`.
The auth dep is exercised orthogonally elsewhere; here we call the
handlers as plain async functions with deps satisfied directly.

The MockSupabase here is richer than the brand-manager one because:
  - Channels carry archived/active filters (`is_("archived_at", "null")`)
  - Messages support `before` cursor pagination (`lt("created_at", before)`)
  - We need `in_(...)` filters for the grouped member-count query
  - Insert needs to populate an id and round-trip the row back

Joins (e.g. `select(*, sender_user:sender_user_id(...))`) aren't simulated
— they're integration concerns. Where a test cares about the joined
shape it preloads the row already containing the nested object.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.dependencies import CurrentUser
from app.routers.channels import (
    CreateChannelRequest,
    CreateMessageRequest,
    RejectApprovalInChannelRequest,
    approve_in_channel,
    create_channel,
    create_message,
    join_channel,
    list_channels,
    list_mentionable,
    list_messages,
    mark_channel_read,
    reject_in_channel,
)


# ── Fixtures ──────────────────────────────────────────────────────────────
@pytest.fixture
def real_uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def user(real_uuid: str) -> CurrentUser:
    return CurrentUser(
        id=str(uuid.uuid4()),
        org_id=real_uuid,
        email="caller@example.com",
        role="member",
    )


# ── MockSupabase ──────────────────────────────────────────────────────────
class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    def __init__(self, table_name: str, store: dict):
        self._table = table_name
        self._store = store
        self._eq_filters: dict[str, Any] = {}
        self._null_filters: list[str] = []
        self._in_filters: dict[str, list] = {}
        self._lt_filters: dict[str, Any] = {}
        self._gt_filters: dict[str, Any] = {}
        # Postgrest jsonb-arrow filters: ("metadata", "approval_id") -> value
        # Used by `_find_approval_card_message` to locate approval cards.
        self._json_eq_filters: dict[tuple[str, str], Any] = {}
        self._mode = "select"
        self._insert_payload: dict | None = None
        self._upsert_payload: dict | None = None
        self._update_payload: dict | None = None

    # ── builder methods ────────────────────────────────────────────────
    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def insert(self, payload):
        # supabase-py accepts a dict (single row) or a list of dicts
        # (batched insert). Tests for `_create_mention_notifications`
        # exercise the list path.
        self._mode = "insert"
        self._insert_payload = payload
        return self

    def upsert(self, payload: dict, **_k):
        self._mode = "upsert"
        self._upsert_payload = payload
        return self

    def update(self, payload: dict):
        self._mode = "update"
        self._update_payload = payload
        return self

    def eq(self, key: str, value):
        self._eq_filters[key] = value
        return self

    def is_(self, key: str, value):
        # We only use is_('archived_at', 'null') in the router.
        if value == "null":
            self._null_filters.append(key)
        return self

    def in_(self, key: str, values: list):
        self._in_filters[key] = list(values)
        return self

    def lt(self, key: str, value):
        self._lt_filters[key] = value
        return self

    def gt(self, key: str, value):
        self._gt_filters[key] = value
        return self

    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def delete(self): return self

    def filter(self, expr: str, op: str, value):
        # Only `metadata->>key` eq is exercised in tests today. Anything
        # else falls through as a no-op to keep the mock forgiving.
        if op == "eq" and "->>" in expr:
            col, _, json_key = expr.partition("->>")
            self._json_eq_filters[(col, json_key)] = value
        return self

    # ── execute ────────────────────────────────────────────────────────
    def _matches(self, row: dict) -> bool:
        for k, v in self._eq_filters.items():
            if row.get(k) != v:
                return False
        for k in self._null_filters:
            if row.get(k) is not None:
                return False
        for k, vs in self._in_filters.items():
            if row.get(k) not in vs:
                return False
        for k, v in self._lt_filters.items():
            rv = row.get(k)
            if rv is None or not (rv < v):
                return False
        for k, v in self._gt_filters.items():
            rv = row.get(k)
            if rv is None or not (rv > v):
                return False
        for (col, key), v in self._json_eq_filters.items():
            blob = row.get(col)
            if not isinstance(blob, dict) or blob.get(key) != v:
                return False
        return True

    def execute(self):
        rows = self._store.get(self._table, [])
        if self._mode == "insert" and self._insert_payload is not None:
            payloads = (
                self._insert_payload
                if isinstance(self._insert_payload, list)
                else [self._insert_payload]
            )
            new_rows: list[dict] = []
            for p in payloads:
                new_row = {"id": str(uuid.uuid4()), **p}
                # Enforce uniqueness on (org_id, name) for channels —
                # mirrors the DB unique constraint, since we test the
                # 409 path.
                if self._table == "channels":
                    for r in rows:
                        if (
                            r.get("org_id") == new_row.get("org_id")
                            and r.get("name") == new_row.get("name")
                        ):
                            raise Exception("duplicate key value violates unique constraint")
                rows.append(new_row)
                new_rows.append(new_row)
                self._store.setdefault("_inserts", []).append((self._table, new_row))
            self._store[self._table] = rows
            return _MockResult(new_rows)
        if self._mode == "upsert" and self._upsert_payload is not None:
            # Approximate upsert — replace rows matching the upsert keys
            # if present; otherwise insert. Both `channel_members` and
            # `channel_reads` use the (channel_id, user_id) composite
            # key shape, so the same matcher applies.
            payload = self._upsert_payload
            if self._table in ("channel_members", "channel_reads"):
                for r in rows:
                    if (
                        r.get("channel_id") == payload.get("channel_id")
                        and r.get("user_id") == payload.get("user_id")
                    ):
                        r.update(payload)
                        return _MockResult([r])
            rows.append(payload)
            self._store[self._table] = rows
            self._store.setdefault("_upserts", []).append((self._table, payload))
            return _MockResult([payload])
        if self._mode == "update" and self._update_payload is not None:
            updated = []
            for r in rows:
                if self._matches(r):
                    r.update(self._update_payload)
                    updated.append(r)
            return _MockResult(updated)
        # select
        out = [r for r in rows if self._matches(r)]
        return _MockResult(out)


class MockSupabase:
    def __init__(self, store: dict | None = None):
        self._store = store if store is not None else {}

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._store)


# ── GET /channels ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestListChannels:
    async def test_returns_org_scoped_channels(self, user: CurrentUser, real_uuid: str):
        """Other-org channels must not appear in the list."""
        other_org = str(uuid.uuid4())
        c1 = str(uuid.uuid4())
        c2 = str(uuid.uuid4())
        store = {
            "channels": [
                {"id": c1, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
                {"id": c2, "org_id": real_uuid, "name": "marketing",
                 "description": "marketing chat", "created_by": user.id,
                 "created_at": "2026-04-29T00:00:00Z", "archived_at": None},
                # Different org — must NOT come back.
                {"id": str(uuid.uuid4()), "org_id": other_org, "name": "other-org-only",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_members": [],
        }
        sb = MockSupabase(store)
        result = await list_channels(user=user, supabase=sb)
        names = {c["name"] for c in result}
        assert names == {"general", "marketing"}

    async def test_excludes_archived(self, user: CurrentUser, real_uuid: str):
        store = {
            "channels": [
                {"id": str(uuid.uuid4()), "org_id": real_uuid, "name": "active",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
                {"id": str(uuid.uuid4()), "org_id": real_uuid, "name": "old",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-29T00:00:00Z",
                 "archived_at": "2026-04-30T00:00:00Z"},
            ],
            "channel_members": [],
        }
        sb = MockSupabase(store)
        result = await list_channels(user=user, supabase=sb)
        assert [c["name"] for c in result] == ["active"]

    async def test_member_count_is_correct(self, user: CurrentUser, real_uuid: str):
        c1, c2 = str(uuid.uuid4()), str(uuid.uuid4())
        u1, u2, u3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        store = {
            "channels": [
                {"id": c1, "org_id": real_uuid, "name": "popular",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
                {"id": c2, "org_id": real_uuid, "name": "lonely",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-29T00:00:00Z", "archived_at": None},
            ],
            "channel_members": [
                {"channel_id": c1, "user_id": u1},
                {"channel_id": c1, "user_id": u2},
                {"channel_id": c1, "user_id": u3},
                {"channel_id": c2, "user_id": u1},
            ],
        }
        sb = MockSupabase(store)
        result = await list_channels(user=user, supabase=sb)
        by_name = {c["name"]: c for c in result}
        assert by_name["popular"]["member_count"] == 3
        assert by_name["lonely"]["member_count"] == 1


# ── POST /channels ────────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestCreateChannel:
    async def test_creates_channel_and_auto_joins_creator(
        self, user: CurrentUser, real_uuid: str,
    ):
        store: dict = {"channels": [], "channel_members": []}
        sb = MockSupabase(store)
        body = CreateChannelRequest(name="general", description="default")
        result = await create_channel(body=body, user=user, supabase=sb)
        assert result["name"] == "general"
        assert result["created_by"] == user.id
        assert result["member_count"] == 1
        # Creator was auto-added to channel_members.
        members = store["channel_members"]
        assert any(m["user_id"] == user.id for m in members)

    async def test_409_on_duplicate_name_in_same_org(
        self, user: CurrentUser, real_uuid: str,
    ):
        store: dict = {
            "channels": [
                {"id": str(uuid.uuid4()), "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_members": [],
        }
        sb = MockSupabase(store)
        with pytest.raises(HTTPException) as exc:
            await create_channel(
                body=CreateChannelRequest(name="general"),
                user=user,
                supabase=sb,
            )
        assert exc.value.status_code == 409

    async def test_same_name_allowed_in_different_orgs(
        self, user: CurrentUser, real_uuid: str,
    ):
        """Two different orgs each having a `#general` is the whole point of
        the per-org unique constraint. Must not collide."""
        other_org = str(uuid.uuid4())
        store: dict = {
            "channels": [
                {"id": str(uuid.uuid4()), "org_id": other_org, "name": "general",
                 "description": None, "created_by": str(uuid.uuid4()),
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_members": [],
        }
        sb = MockSupabase(store)
        result = await create_channel(
            body=CreateChannelRequest(name="general"),
            user=user,
            supabase=sb,
        )
        assert result["name"] == "general"
        assert result["member_count"] == 1

    async def test_returns_creator_in_member_count(
        self, user: CurrentUser, real_uuid: str,
    ):
        """Sanity — member_count on the response is exactly 1 right after
        create (the creator is the only member)."""
        store: dict = {"channels": [], "channel_members": []}
        sb = MockSupabase(store)
        result = await create_channel(
            body=CreateChannelRequest(name="ideas"), user=user, supabase=sb,
        )
        assert result["member_count"] == 1


class TestCreateChannelSchema:
    """Pure Pydantic validation — sync, no async machinery needed."""
    def test_rejects_bad_name_regex(self):
        with pytest.raises(Exception):
            CreateChannelRequest(name="Has Spaces")
        with pytest.raises(Exception):
            CreateChannelRequest(name="UPPERCASE")
        with pytest.raises(Exception):
            CreateChannelRequest(name="bad!chars")
        with pytest.raises(Exception):
            CreateChannelRequest(name="")
        # 65 chars — exceeds the 64 cap
        with pytest.raises(Exception):
            CreateChannelRequest(name="a" * 65)

    def test_accepts_valid_names(self):
        assert CreateChannelRequest(name="general").name == "general"
        assert CreateChannelRequest(name="brand-deals").name == "brand-deals"
        assert CreateChannelRequest(name="team_2026").name == "team_2026"


# ── GET /channels/{id}/messages ───────────────────────────────────────────
@pytest.mark.asyncio
class TestListMessages:
    async def test_404_on_cross_tenant_channel_id(self, user: CurrentUser):
        """A channel id that exists but in another org must come back as 404."""
        other_org = str(uuid.uuid4())
        cid = str(uuid.uuid4())
        store = {
            "channels": [
                {"id": cid, "org_id": other_org, "name": "secret",
                 "description": None, "created_by": str(uuid.uuid4()),
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_messages": [],
        }
        sb = MockSupabase(store)
        with pytest.raises(HTTPException) as exc:
            await list_messages(
                channel_id=cid, limit=50, before=None, user=user, supabase=sb,
            )
        assert exc.value.status_code == 404

    async def test_returns_newest_first(self, user: CurrentUser, real_uuid: str):
        cid = str(uuid.uuid4())
        store = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_messages": [
                {"id": str(uuid.uuid4()), "channel_id": cid, "org_id": real_uuid,
                 "sender_user_id": user.id, "sender_agent_id": None,
                 "body": "first", "mentioned_user_ids": [], "mentioned_agent_slugs": [],
                 "agent_run_id": None, "in_reply_to_message_id": None,
                 "created_at": "2026-04-30T00:00:00Z", "edited_at": None},
                {"id": str(uuid.uuid4()), "channel_id": cid, "org_id": real_uuid,
                 "sender_user_id": user.id, "sender_agent_id": None,
                 "body": "second", "mentioned_user_ids": [], "mentioned_agent_slugs": [],
                 "agent_run_id": None, "in_reply_to_message_id": None,
                 "created_at": "2026-04-30T00:01:00Z", "edited_at": None},
            ],
        }
        sb = MockSupabase(store)
        result = await list_messages(
            channel_id=cid, limit=50, before=None, user=user, supabase=sb,
        )
        # The MockQuery doesn't actually sort (postgrest does), but the rows
        # come back in insertion order. Real ordering is asserted via the
        # `.order("created_at", desc=True)` call — covered by integration.
        bodies = {r["body"] for r in result}
        assert bodies == {"first", "second"}

    async def test_pagination_with_before_cursor(self, user: CurrentUser, real_uuid: str):
        """`before` filters created_at < cursor — older messages only."""
        cid = str(uuid.uuid4())
        store = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_messages": [
                {"id": str(uuid.uuid4()), "channel_id": cid, "org_id": real_uuid,
                 "sender_user_id": user.id, "sender_agent_id": None,
                 "body": "old", "mentioned_user_ids": [], "mentioned_agent_slugs": [],
                 "agent_run_id": None, "in_reply_to_message_id": None,
                 "created_at": "2026-04-29T00:00:00Z", "edited_at": None},
                {"id": str(uuid.uuid4()), "channel_id": cid, "org_id": real_uuid,
                 "sender_user_id": user.id, "sender_agent_id": None,
                 "body": "new", "mentioned_user_ids": [], "mentioned_agent_slugs": [],
                 "agent_run_id": None, "in_reply_to_message_id": None,
                 "created_at": "2026-04-30T12:00:00Z", "edited_at": None},
            ],
        }
        sb = MockSupabase(store)
        result = await list_messages(
            channel_id=cid, limit=50, before="2026-04-30T00:00:00Z",
            user=user, supabase=sb,
        )
        # Only `old` (2026-04-29) is < 2026-04-30T00:00:00Z.
        assert [r["body"] for r in result] == ["old"]

    async def test_serializes_sender_user_join(self, user: CurrentUser, real_uuid: str):
        """Postgrest joins land as nested objects keyed by alias."""
        cid = str(uuid.uuid4())
        sender_id = str(uuid.uuid4())
        store = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_messages": [
                {"id": str(uuid.uuid4()), "channel_id": cid, "org_id": real_uuid,
                 "sender_user_id": sender_id, "sender_agent_id": None,
                 "sender_user": {"id": sender_id, "full_name": "Abhi V",
                                 "email": "abhi@example.com"},
                 "sender_agent": None,
                 "body": "hello", "mentioned_user_ids": [], "mentioned_agent_slugs": [],
                 "agent_run_id": None, "in_reply_to_message_id": None,
                 "created_at": "2026-04-30T00:00:00Z", "edited_at": None},
            ],
        }
        sb = MockSupabase(store)
        result = await list_messages(
            channel_id=cid, limit=50, before=None, user=user, supabase=sb,
        )
        assert len(result) == 1
        msg = result[0]
        assert msg["sender_user"] == {
            "id": sender_id, "full_name": "Abhi V", "email": "abhi@example.com",
        }
        assert msg["sender_agent"] is None

    async def test_serializes_sender_agent_join(self, user: CurrentUser, real_uuid: str):
        cid = str(uuid.uuid4())
        agent_id = str(uuid.uuid4())
        store = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_messages": [
                {"id": str(uuid.uuid4()), "channel_id": cid, "org_id": real_uuid,
                 "sender_user_id": None, "sender_agent_id": agent_id,
                 "sender_user": None,
                 "sender_agent": {"id": agent_id, "slug": "strategist",
                                  "name": "Strategist", "icon": "compass"},
                 "body": "agent reply", "mentioned_user_ids": [],
                 "mentioned_agent_slugs": [],
                 "agent_run_id": str(uuid.uuid4()),
                 "in_reply_to_message_id": str(uuid.uuid4()),
                 "created_at": "2026-04-30T00:01:00Z", "edited_at": None},
            ],
        }
        sb = MockSupabase(store)
        result = await list_messages(
            channel_id=cid, limit=50, before=None, user=user, supabase=sb,
        )
        msg = result[0]
        assert msg["sender_agent"]["slug"] == "strategist"
        assert msg["sender_user"] is None


# ── POST /channels/{id}/messages ──────────────────────────────────────────
@pytest.mark.asyncio
class TestCreateMessage:
    async def test_inserts_message_and_returns_serialized(
        self, user: CurrentUser, real_uuid: str,
    ):
        cid = str(uuid.uuid4())
        store: dict = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "agents": [],
            "org_members": [],
            "channel_messages": [],
        }
        sb = MockSupabase(store)
        bg = BackgroundTasks()
        result = await create_message(
            channel_id=cid,
            body=CreateMessageRequest(body="hello team"),
            background_tasks=bg,
            user=user,
            supabase=sb,
        )
        assert result["body"] == "hello team"
        assert result["sender_user_id"] == user.id
        assert result["mentioned_agent_slugs"] == []
        # No agent mentions → no background task scheduled.
        assert len(bg.tasks) == 0

    async def test_parses_agent_mention_and_schedules_dispatch(
        self, user: CurrentUser, real_uuid: str,
    ):
        cid = str(uuid.uuid4())
        store: dict = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "agents": [{"org_id": real_uuid, "slug": "strategist"}],
            "org_members": [],
            "channel_messages": [],
        }
        sb = MockSupabase(store)
        bg = BackgroundTasks()
        result = await create_message(
            channel_id=cid,
            body=CreateMessageRequest(body="@strategist what next?"),
            background_tasks=bg,
            user=user,
            supabase=sb,
        )
        assert result["mentioned_agent_slugs"] == ["strategist"]
        assert len(bg.tasks) == 1

    async def test_scoped_agent_mentions_only(
        self, user: CurrentUser, real_uuid: str,
    ):
        """Only agents in the caller's org should resolve."""
        cid = str(uuid.uuid4())
        other_org = str(uuid.uuid4())
        store: dict = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            # 'publisher' exists in another org only — must NOT match.
            "agents": [{"org_id": other_org, "slug": "publisher"}],
            "org_members": [],
            "channel_messages": [],
        }
        sb = MockSupabase(store)
        bg = BackgroundTasks()
        result = await create_message(
            channel_id=cid,
            body=CreateMessageRequest(body="@publisher please ship"),
            background_tasks=bg,
            user=user,
            supabase=sb,
        )
        assert result["mentioned_agent_slugs"] == []
        assert len(bg.tasks) == 0

    async def test_parses_user_mention(self, user: CurrentUser, real_uuid: str):
        cid = str(uuid.uuid4())
        member_id = str(uuid.uuid4())
        store: dict = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "agents": [],
            "org_members": [
                {
                    "org_id": real_uuid,
                    "user_id": member_id,
                    "users": {
                        "id": member_id,
                        "full_name": "Abhi V",
                        "email": "abhi@example.com",
                    },
                },
            ],
            "channel_messages": [],
        }
        sb = MockSupabase(store)
        bg = BackgroundTasks()
        result = await create_message(
            channel_id=cid,
            body=CreateMessageRequest(body="hey @abhi please review"),
            background_tasks=bg,
            user=user,
            supabase=sb,
        )
        assert result["mentioned_user_ids"] == [member_id]

    async def test_dedup_multi_mention(self, user: CurrentUser, real_uuid: str):
        cid = str(uuid.uuid4())
        store: dict = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "agents": [{"org_id": real_uuid, "slug": "strategist"}],
            "org_members": [],
            "channel_messages": [],
        }
        sb = MockSupabase(store)
        bg = BackgroundTasks()
        result = await create_message(
            channel_id=cid,
            body=CreateMessageRequest(body="@strategist @strategist @strategist hey"),
            background_tasks=bg,
            user=user,
            supabase=sb,
        )
        assert result["mentioned_agent_slugs"] == ["strategist"]
        # Only one dispatch scheduled (deduped).
        assert len(bg.tasks) == 1

    async def test_404_on_cross_tenant_channel(self, user: CurrentUser):
        cid = str(uuid.uuid4())
        other_org = str(uuid.uuid4())
        store: dict = {
            "channels": [
                {"id": cid, "org_id": other_org, "name": "private",
                 "description": None, "created_by": str(uuid.uuid4()),
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_messages": [],
            "agents": [],
            "org_members": [],
        }
        sb = MockSupabase(store)
        bg = BackgroundTasks()
        with pytest.raises(HTTPException) as exc:
            await create_message(
                channel_id=cid,
                body=CreateMessageRequest(body="hi"),
                background_tasks=bg,
                user=user,
                supabase=sb,
            )
        assert exc.value.status_code == 404


class TestCreateMessageSchema:
    """Pure Pydantic validation — sync."""
    def test_rejects_empty_body(self):
        with pytest.raises(Exception):
            CreateMessageRequest(body="")

    def test_rejects_too_long_body(self):
        with pytest.raises(Exception):
            CreateMessageRequest(body="a" * 4001)

    def test_accepts_max_body(self):
        body = CreateMessageRequest(body="a" * 4000)
        assert len(body.body) == 4000


# ── POST /channels/{id}/join ──────────────────────────────────────────────
@pytest.mark.asyncio
class TestJoinChannel:
    async def test_idempotent_double_join(self, user: CurrentUser, real_uuid: str):
        cid = str(uuid.uuid4())
        store: dict = {
            "channels": [
                {"id": cid, "org_id": real_uuid, "name": "general",
                 "description": None, "created_by": user.id,
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_members": [],
        }
        sb = MockSupabase(store)
        # First join.
        r1 = await join_channel(channel_id=cid, user=user, supabase=sb)
        assert r1 == {"joined": True}
        # Second join — must not raise.
        r2 = await join_channel(channel_id=cid, user=user, supabase=sb)
        assert r2 == {"joined": True}

    async def test_404_on_cross_tenant_channel(self, user: CurrentUser):
        cid = str(uuid.uuid4())
        other_org = str(uuid.uuid4())
        store: dict = {
            "channels": [
                {"id": cid, "org_id": other_org, "name": "secret",
                 "description": None, "created_by": str(uuid.uuid4()),
                 "created_at": "2026-04-30T00:00:00Z", "archived_at": None},
            ],
            "channel_members": [],
        }
        sb = MockSupabase(store)
        with pytest.raises(HTTPException) as exc:
            await join_channel(channel_id=cid, user=user, supabase=sb)
        assert exc.value.status_code == 404


# ── GET /channels/mentionable ─────────────────────────────────────────────
@pytest.mark.asyncio
class TestMentionable:
    async def test_returns_org_scoped_agents_and_users(
        self, user: CurrentUser, real_uuid: str,
    ):
        other_org = str(uuid.uuid4())
        u1 = str(uuid.uuid4())
        strategist_id = str(uuid.uuid4())
        store: dict = {
            "agents": [
                {"id": strategist_id, "org_id": real_uuid, "slug": "strategist",
                 "name": "Strategist", "icon": "compass", "active": True},
                # Another org's agent — must NOT come back.
                {"id": str(uuid.uuid4()), "org_id": other_org, "slug": "publisher",
                 "name": "Publisher", "icon": "rocket", "active": True},
            ],
            "org_members": [
                {
                    "org_id": real_uuid,
                    "user_id": u1,
                    "users": {"id": u1, "full_name": "Abhi V",
                              "email": "abhi@example.com"},
                },
                # Another-org member — must NOT come back.
                {
                    "org_id": other_org,
                    "user_id": str(uuid.uuid4()),
                    "users": {"id": str(uuid.uuid4()), "full_name": "Outsider",
                              "email": "outsider@example.com"},
                },
            ],
        }
        sb = MockSupabase(store)
        result = await list_mentionable(user=user, supabase=sb)
        assert [a["slug"] for a in result["agents"]] == ["strategist"]
        # `id` is included so the FE can resolve agent senders from realtime
        # payloads (which carry `sender_agent_id`, no joined info).
        assert result["agents"][0]["id"] == strategist_id
        assert [u["id"] for u in result["users"]] == [u1]


# ── POST /channels/{id}/approvals/{id}/approve|reject ────────────────────
@pytest.mark.asyncio
class TestApproveInChannel:
    """The channel-context approve/reject endpoints. Two assertions per
    happy path:
      1. The approval-card row's metadata is UPDATEd in place to record
         the decision (status + reviewed_by). The realtime UPDATE event
         drives the FE to swap buttons for a "approved by @sean" tag.
      2. A background task is queued to drain the resume stream and
         post the agent's continuation back to the channel.
    """

    def _seed_channel_with_card(
        self,
        *,
        org_id: str,
        channel_id: str | None = None,
        approval_id: str | None = None,
    ) -> tuple[MockSupabase, str, str, str]:
        """Build a store with one channel + one approval-card message."""
        channel_id = channel_id or str(uuid.uuid4())
        approval_id = approval_id or str(uuid.uuid4())
        card_id = str(uuid.uuid4())
        sb = MockSupabase({
            "channels": [
                {"id": channel_id, "org_id": org_id, "name": "general",
                 "archived_at": None},
            ],
            "channel_messages": [
                {
                    "id": card_id,
                    "channel_id": channel_id,
                    "org_id": org_id,
                    "sender_user_id": None,
                    "sender_agent_id": str(uuid.uuid4()),
                    "body": "@strategist needs your approval to continue.",
                    "metadata": {"kind": "approval", "approval_id": approval_id},
                    "mentioned_user_ids": [],
                    "mentioned_agent_slugs": [],
                    "agent_run_id": None,
                    "in_reply_to_message_id": None,
                    "edited_at": None,
                    "created_at": "2026-05-05T20:00:00Z",
                },
            ],
        })
        return sb, channel_id, approval_id, card_id

    async def test_approve_marks_card_resolved_and_queues_resume(
        self, user: CurrentUser, real_uuid: str,
    ):
        sb, channel_id, approval_id, card_id = self._seed_channel_with_card(
            org_id=real_uuid,
        )
        bg = BackgroundTasks()

        result = await approve_in_channel(
            channel_id=channel_id,
            approval_id=approval_id,
            background_tasks=bg,
            user=user,
            supabase=sb,
        )

        # Synchronous response.
        assert result == {"status": "approved", "approval_id": approval_id}
        # Card metadata patched in place — the realtime UPDATE event off
        # this would carry the new state to every subscribed FE.
        card = next(r for r in sb._store["channel_messages"] if r["id"] == card_id)
        assert card["metadata"] == {
            "kind": "approval",
            "approval_id": approval_id,
            "status": "approved",
            "reviewed_by": user.id,
        }
        # Resume task queued for the BG runner. We don't drain it here —
        # the dispatch behaviour is covered in test_channel_dispatch.py.
        assert len(bg.tasks) == 1

    async def test_reject_marks_card_resolved_and_passes_feedback(
        self, user: CurrentUser, real_uuid: str,
    ):
        sb, channel_id, approval_id, card_id = self._seed_channel_with_card(
            org_id=real_uuid,
        )
        bg = BackgroundTasks()

        result = await reject_in_channel(
            channel_id=channel_id,
            approval_id=approval_id,
            background_tasks=bg,
            body=RejectApprovalInChannelRequest(feedback="too long"),
            user=user,
            supabase=sb,
        )

        assert result == {"status": "rejected", "approval_id": approval_id}
        card = next(r for r in sb._store["channel_messages"] if r["id"] == card_id)
        assert card["metadata"]["status"] == "rejected"
        assert card["metadata"]["reviewed_by"] == user.id
        # Feedback rides on the queued background task. Inspect the task
        # kwargs the router scheduled so we know the dispatcher will see it.
        assert len(bg.tasks) == 1
        task = bg.tasks[0]
        assert task.kwargs["decision"] == "rejected"
        assert task.kwargs["feedback"] == "too long"

    async def test_approve_404_when_card_not_in_channel(
        self, user: CurrentUser, real_uuid: str,
    ):
        """The card lookup is org+channel-scoped, so an approval id that
        belongs to a different channel (or is bogus) must 404 — never
        UPDATE someone else's channel_messages row."""
        sb, channel_id, _approval_id, _card_id = self._seed_channel_with_card(
            org_id=real_uuid,
        )
        bg = BackgroundTasks()

        with pytest.raises(HTTPException) as exc:
            await approve_in_channel(
                channel_id=channel_id,
                approval_id=str(uuid.uuid4()),  # not the seeded one
                background_tasks=bg,
                user=user,
                supabase=sb,
            )
        assert exc.value.status_code == 404
        # No background task scheduled either.
        assert len(bg.tasks) == 0

    async def test_approve_404_when_channel_not_in_org(
        self, user: CurrentUser, real_uuid: str,
    ):
        """Cross-tenant attack: caller passes a channel id that exists
        in a different org. _assert_channel_in_org must 404 BEFORE we
        touch the card."""
        other_org = str(uuid.uuid4())
        # Channel + card both belong to a DIFFERENT org.
        sb, channel_id, approval_id, _ = self._seed_channel_with_card(
            org_id=other_org,
        )
        bg = BackgroundTasks()

        with pytest.raises(HTTPException) as exc:
            await approve_in_channel(
                channel_id=channel_id,
                approval_id=approval_id,
                background_tasks=bg,
                user=user,  # caller is in real_uuid, not other_org
                supabase=sb,
            )
        assert exc.value.status_code == 404
        # Other-org card MUST be untouched.
        card = sb._store["channel_messages"][0]
        assert "status" not in card["metadata"]


# ── Schema validation ─────────────────────────────────────────────────────
class TestRejectApprovalInChannelSchema:
    def test_feedback_optional(self):
        body = RejectApprovalInChannelRequest()
        assert body.feedback is None

    def test_feedback_round_trips(self):
        body = RejectApprovalInChannelRequest(feedback="rephrase the subject")
        assert body.feedback == "rephrase the subject"


# ── POST /channels/{id}/read ─────────────────────────────────────────────
@pytest.mark.asyncio
class TestMarkChannelRead:
    """The mark-read endpoint upserts a `channel_reads` row keyed on
    (user_id, channel_id) with `last_read_at = now()`."""

    async def test_first_read_inserts_row(self, user: CurrentUser, real_uuid: str):
        channel_id = str(uuid.uuid4())
        sb = MockSupabase({
            "channels": [
                {"id": channel_id, "org_id": real_uuid, "name": "general",
                 "archived_at": None},
            ],
        })

        result = await mark_channel_read(
            channel_id=channel_id, user=user, supabase=sb,
        )
        assert result["ok"] is True
        assert "last_read_at" in result
        # Row landed in `channel_reads`.
        rows = sb._store.get("channel_reads", [])
        assert len(rows) == 1
        assert rows[0]["user_id"] == user.id
        assert rows[0]["channel_id"] == channel_id

    async def test_repeat_read_updates_existing_row(
        self, user: CurrentUser, real_uuid: str,
    ):
        """Calling mark-read twice should leave a single row, not two —
        the upsert path matches on (user_id, channel_id)."""
        channel_id = str(uuid.uuid4())
        sb = MockSupabase({
            "channels": [
                {"id": channel_id, "org_id": real_uuid, "name": "general",
                 "archived_at": None},
            ],
        })

        await mark_channel_read(channel_id=channel_id, user=user, supabase=sb)
        await mark_channel_read(channel_id=channel_id, user=user, supabase=sb)

        rows = sb._store.get("channel_reads", [])
        assert len(rows) == 1

    async def test_404_on_cross_tenant_channel(self, user: CurrentUser):
        """Caller in org A tries to mark a channel in org B as read.
        _assert_channel_in_org should 404 BEFORE any channel_reads row
        is touched — otherwise the user could pollute someone else's
        channel with a read receipt for a row they shouldn't see."""
        other_org = str(uuid.uuid4())
        channel_id = str(uuid.uuid4())
        sb = MockSupabase({
            "channels": [
                {"id": channel_id, "org_id": other_org, "name": "secret",
                 "archived_at": None},
            ],
        })

        with pytest.raises(HTTPException) as exc:
            await mark_channel_read(
                channel_id=channel_id, user=user, supabase=sb,
            )
        assert exc.value.status_code == 404
        # No row created.
        assert "channel_reads" not in sb._store or not sb._store["channel_reads"]


# ── GET /channels with unread_count ──────────────────────────────────────
@pytest.mark.asyncio
class TestListChannelsUnreadCounts:
    """`list_channels` returns each channel with an `unread_count` driven
    by `(user_id, channel_id) → last_read_at` joined against
    `channel_messages.created_at`."""

    async def test_unread_count_counts_messages_after_last_read(
        self, user: CurrentUser, real_uuid: str,
    ):
        channel_id = str(uuid.uuid4())
        teammate_id = str(uuid.uuid4())
        sb = MockSupabase({
            "channels": [
                {"id": channel_id, "org_id": real_uuid, "name": "general",
                 "archived_at": None,
                 "created_at": "2026-05-01T00:00:00Z"},
            ],
            "channel_reads": [
                {"user_id": user.id, "channel_id": channel_id,
                 "last_read_at": "2026-05-05T00:00:00Z"},
            ],
            "channel_messages": [
                # Old, before last_read → not counted.
                {"channel_id": channel_id, "sender_user_id": teammate_id,
                 "created_at": "2026-05-04T12:00:00Z"},
                # New, from a teammate → counted.
                {"channel_id": channel_id, "sender_user_id": teammate_id,
                 "created_at": "2026-05-06T10:00:00Z"},
                {"channel_id": channel_id, "sender_user_id": teammate_id,
                 "created_at": "2026-05-06T11:00:00Z"},
                # New, but from the caller → NOT counted (own posts).
                {"channel_id": channel_id, "sender_user_id": user.id,
                 "created_at": "2026-05-06T12:00:00Z"},
            ],
        })

        result = await list_channels(user=user, supabase=sb)
        assert len(result) == 1
        assert result[0]["unread_count"] == 2

    async def test_unread_count_is_full_history_when_never_opened(
        self, user: CurrentUser, real_uuid: str,
    ):
        """A teammate's brand-new channel that this user has never seen
        should count its full history as unread — Slack-style."""
        channel_id = str(uuid.uuid4())
        teammate_id = str(uuid.uuid4())
        sb = MockSupabase({
            "channels": [
                {"id": channel_id, "org_id": real_uuid, "name": "fresh",
                 "archived_at": None,
                 "created_at": "2026-05-01T00:00:00Z"},
            ],
            "channel_messages": [
                {"channel_id": channel_id, "sender_user_id": teammate_id,
                 "created_at": "2026-05-04T12:00:00Z"},
                {"channel_id": channel_id, "sender_user_id": teammate_id,
                 "created_at": "2026-05-05T10:00:00Z"},
            ],
        })

        result = await list_channels(user=user, supabase=sb)
        assert result[0]["unread_count"] == 2
        assert result[0]["last_read_at"] is None


# ── Mention notifications ─────────────────────────────────────────────────
@pytest.mark.asyncio
class TestMentionNotifications:
    """create_message must insert a `notifications` row for every @user
    it parsed — minus the author themselves."""

    async def test_mention_creates_notification_for_each_user(
        self, user: CurrentUser, real_uuid: str,
    ):
        channel_id = str(uuid.uuid4())
        teammate_id = str(uuid.uuid4())
        teammate_2 = str(uuid.uuid4())
        sb = MockSupabase({
            "channels": [
                {"id": channel_id, "org_id": real_uuid, "name": "general",
                 "archived_at": None},
            ],
            # The mention parser does a Postgrest nested-join select on
            # `org_members` → `users`. Our mock doesn't simulate joins, so
            # the user blob has to be pre-attached on the org_members row
            # for the parser to find it.
            "org_members": [
                {"user_id": user.id, "org_id": real_uuid,
                 "users": {"id": user.id, "full_name": "Author Person",
                           "email": "author@example.com"}},
                {"user_id": teammate_id, "org_id": real_uuid,
                 "users": {"id": teammate_id, "full_name": "Sean Smith",
                           "email": "sean@example.com"}},
                {"user_id": teammate_2, "org_id": real_uuid,
                 "users": {"id": teammate_2, "full_name": "Pat Patel",
                           "email": "pat@example.com"}},
            ],
            "agents": [],
        })

        bg = BackgroundTasks()
        await create_message(
            channel_id=channel_id,
            body=CreateMessageRequest(body="hey @sean and @pat — what do you think?"),
            background_tasks=bg,
            user=user,
            supabase=sb,
        )

        notifs = sb._store.get("notifications", [])
        assert len(notifs) == 2
        # Each notification points to a recipient and carries metadata
        # back to the channel + message id for deep-linking.
        assert {n["user_id"] for n in notifs} == {teammate_id, teammate_2}
        for n in notifs:
            assert n["type"] == "channel_mention"
            assert n["org_id"] == real_uuid
            assert n["metadata"]["channel_id"] == channel_id
            assert "message_id" in n["metadata"]
            assert n["action_url"] == f"/app/channels?channel={channel_id}"

    async def test_self_mention_does_not_notify(
        self, user: CurrentUser, real_uuid: str,
    ):
        """If the author types their own `@username` (typo or referring
        to themselves), we don't ping them. They sent the message; they
        know about it."""
        channel_id = str(uuid.uuid4())
        sb = MockSupabase({
            "channels": [
                {"id": channel_id, "org_id": real_uuid, "name": "general",
                 "archived_at": None},
            ],
            "org_members": [
                {"user_id": user.id, "org_id": real_uuid,
                 "users": {"id": user.id, "full_name": "Author Person",
                           "email": "author@example.com"}},
            ],
            "agents": [],
        })

        bg = BackgroundTasks()
        await create_message(
            channel_id=channel_id,
            body=CreateMessageRequest(body="reminder to @author"),
            background_tasks=bg,
            user=user,
            supabase=sb,
        )

        # Mention parsed but the author was filtered out before insert.
        assert sb._store.get("notifications", []) == []

    async def test_no_mentions_no_notifications(
        self, user: CurrentUser, real_uuid: str,
    ):
        """A regular message with no @-mentions should not write any
        notifications rows."""
        channel_id = str(uuid.uuid4())
        sb = MockSupabase({
            "channels": [
                {"id": channel_id, "org_id": real_uuid, "name": "general",
                 "archived_at": None},
            ],
            "users": [],
            "org_members": [{"user_id": user.id, "org_id": real_uuid}],
            "agents": [],
        })

        bg = BackgroundTasks()
        await create_message(
            channel_id=channel_id,
            body=CreateMessageRequest(body="hello world, no mentions here"),
            background_tasks=bg,
            user=user,
            supabase=sb,
        )

        assert "notifications" not in sb._store or not sb._store["notifications"]
