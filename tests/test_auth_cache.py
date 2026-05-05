"""
Auth-token cache — unit tests on `TtlCache` and integration tests
verifying `get_current_user` / `get_authenticated_user` actually
short-circuit on a cache hit (no second JWT verify, no second
org_members lookup).

The integration tests reuse the MockSupabase shape from
`test_auto_provisioner_gate.py` so we can count how many times
`supabase.auth.get_user` and `supabase.table().execute()` are called
across two sequential resolves with the same token.
"""
from __future__ import annotations

import time
import uuid
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request

from app.auth_cache import TtlCache
from app.dependencies import (
    _authenticated_user_cache,
    _current_user_cache,
    get_authenticated_user,
    get_current_user,
)


# ── Module-level cache hygiene ────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clear_module_caches():
    _current_user_cache.clear()
    _authenticated_user_cache.clear()
    yield
    _current_user_cache.clear()
    _authenticated_user_cache.clear()


# ── Unit tests on the cache primitive ─────────────────────────────────────
class TestTtlCache:
    def test_set_then_get_returns_value(self):
        cache: TtlCache[str] = TtlCache()
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_miss_returns_none(self):
        cache: TtlCache[str] = TtlCache()
        assert cache.get("nope") is None

    def test_expires_after_ttl(self):
        """Past the TTL the entry is gone — not just stale."""
        cache: TtlCache[str] = TtlCache(ttl_seconds=0.01)
        cache.set("k", "v")
        time.sleep(0.02)
        assert cache.get("k") is None
        # And it was actually evicted, not just hidden.
        assert cache.size() == 0

    def test_different_keys_isolated(self):
        cache: TtlCache[str] = TtlCache()
        cache.set("a", "first")
        cache.set("b", "second")
        assert cache.get("a") == "first"
        assert cache.get("b") == "second"

    def test_invalidate_drops_specific_entry(self):
        cache: TtlCache[str] = TtlCache()
        cache.set("a", "x")
        cache.set("b", "y")
        cache.invalidate("a")
        assert cache.get("a") is None
        assert cache.get("b") == "y"

    def test_clear_drops_everything(self):
        cache: TtlCache[str] = TtlCache()
        cache.set("a", "x")
        cache.set("b", "y")
        cache.clear()
        assert cache.size() == 0

    def test_set_again_resets_ttl(self):
        """Re-setting an existing key extends its life — handy if we ever
        want a "touch on access" pattern. Today we just always re-set on
        cache miss, so this is the property that keeps a hot token alive."""
        cache: TtlCache[str] = TtlCache(ttl_seconds=0.05)
        cache.set("k", "v1")
        time.sleep(0.03)
        cache.set("k", "v2")  # reset — full TTL again
        time.sleep(0.03)
        # If TTL didn't reset on the second set, this would be expired.
        assert cache.get("k") == "v2"

    def test_evicts_oldest_when_over_max(self):
        """Soft cap — first inserted entry should age out when the cap
        is exceeded. Protects against a forged-token DoS unbounding the
        dict."""
        cache: TtlCache[str] = TtlCache(max_size=3)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")
        cache.set("d", "4")
        # 'a' was the oldest — should have been evicted.
        assert cache.get("a") is None
        # The newer ones survive.
        assert cache.get("d") == "4"
        assert cache.size() == 3


# ── Integration: MockSupabase counting how many times auth/db are hit ────


class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    def __init__(self, table: str, store: dict, exec_counter: list[int]):
        self._table = table
        self._store = store
        self._mode = "select"
        self._payload: Any = None
        self._eq: list[tuple[str, Any]] = []
        self._is_null: list[str] = []
        self._exec_counter = exec_counter

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict: str | None = None, **_k):
        self._mode = "upsert"
        self._payload = payload
        self._upsert_conflict = on_conflict
        return self

    def eq(self, k, v):
        self._eq.append((k, v))
        return self

    def is_(self, k, v):
        if v == "null":
            self._is_null.append(k)
        return self

    def limit(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self

    def _matches(self, row):
        for k, v in self._eq:
            if row.get(k) != v:
                return False
        for k in self._is_null:
            if row.get(k) is not None:
                return False
        return True

    def execute(self):
        self._exec_counter[0] += 1
        rows = self._store.setdefault(self._table, [])
        if self._mode == "insert":
            new_row = dict(self._payload)
            new_row.setdefault("id", str(uuid.uuid4()))
            rows.append(new_row)
            return _MockResult([deepcopy(new_row)])
        if self._mode == "upsert":
            conflict_cols = ((getattr(self, "_upsert_conflict", None) or "id")).split(",")
            for r in rows:
                if all(r.get(c) == self._payload.get(c) for c in conflict_cols):
                    r.update(self._payload)
                    return _MockResult([deepcopy(r)])
            new_row = dict(self._payload)
            new_row.setdefault("id", str(uuid.uuid4()))
            rows.append(new_row)
            return _MockResult([deepcopy(new_row)])
        # select
        return _MockResult([deepcopy(r) for r in rows if self._matches(r)])


class CountingMockSupabase:
    """MagicMock's built-in `call_count` does the counting for free —
    no wrapping needed. `db_executes` is a 1-element list so the inner
    `_MockQuery` can mutate the count without us holding a back-ref."""

    def __init__(self, store: dict | None = None):
        self.store = store or {}
        self.auth = MagicMock()
        self.db_executes = [0]

    @property
    def auth_calls(self) -> int:
        return self.auth.get_user.call_count

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self.store, self.db_executes)


def _stub_user(sb: CountingMockSupabase, *, user_id: str, email: str) -> None:
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.user_metadata = {"full_name": "Test User"}
    user_response = MagicMock()
    user_response.user = user
    sb.auth.get_user.return_value = user_response


def _make_request_with(token: str = "fake.jwt.token") -> Request:
    scope = {
        "type": "http",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
    return Request(scope)


# ── get_current_user cache integration ────────────────────────────────────
@pytest.mark.asyncio
class TestGetCurrentUserCache:
    async def test_cache_hit_skips_auth_and_db(self):
        """Two calls with the same Bearer token: only the first should
        hit Supabase Auth and the org_members table. The second is a
        pure cache read."""
        user_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())
        sb = CountingMockSupabase({
            "org_members": [
                {"id": str(uuid.uuid4()), "user_id": user_id, "org_id": org_id, "role": "owner"},
            ],
            "org_invites": [],
        })
        _stub_user(sb, user_id=user_id, email="hot@example.com")

        req = _make_request_with()

        first = await get_current_user(request=req, supabase=sb)
        executes_after_first = sb.db_executes[0]
        auth_after_first = sb.auth_calls

        second = await get_current_user(request=req, supabase=sb)

        # Same resolved value.
        assert first.org_id == second.org_id == org_id
        assert first.id == second.id == user_id
        # Second call did NOT hit auth or the DB.
        assert sb.auth_calls == auth_after_first
        assert sb.db_executes[0] == executes_after_first

    async def test_different_tokens_isolated(self):
        """Two distinct Bearer tokens must each verify independently —
        the cache key is the token, not the user id."""
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        sb = CountingMockSupabase({
            "org_members": [
                {"id": str(uuid.uuid4()), "user_id": user_a, "org_id": org_a, "role": "owner"},
                {"id": str(uuid.uuid4()), "user_id": user_b, "org_id": org_b, "role": "owner"},
            ],
            "org_invites": [],
        })

        # Two separate Request objects with different tokens; flip the
        # auth stub between calls so each token resolves to a different
        # user. (Real Supabase Auth would do this naturally based on JWT.)
        req_a = _make_request_with("token-a")
        _stub_user(sb, user_id=user_a, email="a@example.com")
        first_a = await get_current_user(request=req_a, supabase=sb)
        assert first_a.org_id == org_a
        auth_a = sb.auth_calls

        req_b = _make_request_with("token-b")
        _stub_user(sb, user_id=user_b, email="b@example.com")
        first_b = await get_current_user(request=req_b, supabase=sb)
        assert first_b.org_id == org_b
        # token-b was a fresh cache miss → auth was called again.
        assert sb.auth_calls > auth_a

    async def test_invalid_token_not_cached(self):
        """A 401 must be re-raised on every retry, not cached. User
        could be retrying with the same expired token while their FE
        rotates, and we don't want to lock them out for 60s."""
        sb = CountingMockSupabase()
        # Auth says "no user".
        sb.auth.get_user.return_value = MagicMock(user=None)

        req = _make_request_with()
        with pytest.raises(HTTPException) as exc1:
            await get_current_user(request=req, supabase=sb)
        assert exc1.value.status_code == 401

        with pytest.raises(HTTPException) as exc2:
            await get_current_user(request=req, supabase=sb)
        assert exc2.value.status_code == 401

        # Both attempts re-verified — neither was cached.
        assert sb.auth_calls == 2

    async def test_pending_invite_409_not_cached(self):
        """The 409 path is the auto-provisioner gate. The user might be
        about to click their invite link; the next request should
        resolve fresh, not be told 409 again until TTL expiry."""
        invitee_id = str(uuid.uuid4())
        sb = CountingMockSupabase({
            "org_invites": [
                {
                    "id": str(uuid.uuid4()),
                    "org_id": str(uuid.uuid4()),
                    "email": "alice@example.com",
                    "accepted_at": None,
                    "revoked_at": None,
                }
            ],
            "org_members": [],
        })
        _stub_user(sb, user_id=invitee_id, email="alice@example.com")

        req = _make_request_with()
        with pytest.raises(HTTPException) as exc1:
            await get_current_user(request=req, supabase=sb)
        assert exc1.value.status_code == 409

        # Second call must STILL hit the DB to re-check the invite state
        # (in case it just got accepted).
        executes_before = sb.db_executes[0]
        with pytest.raises(HTTPException) as exc2:
            await get_current_user(request=req, supabase=sb)
        assert exc2.value.status_code == 409
        assert sb.db_executes[0] > executes_before


# ── get_authenticated_user cache integration ──────────────────────────────
@pytest.mark.asyncio
class TestGetAuthenticatedUserCache:
    async def test_cache_hit_skips_auth(self):
        sb = CountingMockSupabase()
        _stub_user(sb, user_id=str(uuid.uuid4()), email="x@example.com")

        req = _make_request_with()
        first = await get_authenticated_user(request=req, supabase=sb)
        auth_after_first = sb.auth_calls

        second = await get_authenticated_user(request=req, supabase=sb)
        assert first.id == second.id
        assert sb.auth_calls == auth_after_first

    async def test_caches_are_separate(self):
        """`get_authenticated_user` and `get_current_user` use different
        caches — a hit on one must not satisfy the other (they return
        different shapes)."""
        user_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())
        sb = CountingMockSupabase({
            "org_members": [
                {"id": str(uuid.uuid4()), "user_id": user_id, "org_id": org_id, "role": "owner"},
            ],
            "org_invites": [],
        })
        _stub_user(sb, user_id=user_id, email="x@example.com")

        req = _make_request_with()
        # Populate the AuthenticatedUser cache.
        _ = await get_authenticated_user(request=req, supabase=sb)
        # get_current_user must NOT pull from that cache — it returns a
        # different dataclass with org context.
        result = await get_current_user(request=req, supabase=sb)
        assert hasattr(result, "org_id")
        assert result.org_id == org_id
