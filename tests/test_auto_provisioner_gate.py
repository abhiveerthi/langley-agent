"""
Auto-provisioner gate — F1 from the eng review.

`get_current_user` in app.dependencies must NOT auto-create a personal
workspace for a user whose email has a pending unaccepted org invite.
Instead it returns 409 telling the user to click their invite link.

Without this gate, the invitee would be auto-provisioned a personal org,
hit the single-org-per-user constraint when accepting the invite, and
get locked out of the inviting workspace.
"""
from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request

from app.dependencies import get_current_user


# ── MockSupabase (subset of test_invites_router.py — kept inline here so
#    this test file is independent and easy to read) ───────────────────────


class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    def __init__(self, table: str, store: dict):
        self._table = table
        self._store = store
        self._mode = "select"
        self._payload: Any = None
        self._eq: list[tuple[str, Any]] = []
        self._is_null: list[str] = []

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

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
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

        if self._mode == "update":
            updated = []
            for r in rows:
                if self._matches(r):
                    r.update(self._payload)
                    updated.append(deepcopy(r))
            return _MockResult(updated)

        # select
        return _MockResult([deepcopy(r) for r in rows if self._matches(r)])


class MockSupabase:
    def __init__(self, store: dict | None = None):
        self.store = store or {}
        self.auth = MagicMock()

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self.store)


def _make_request_with_token() -> Request:
    """Build a minimal Request object with a Bearer auth header."""
    scope = {
        "type": "http",
        "headers": [(b"authorization", b"Bearer fake.jwt.token")],
    }
    return Request(scope)


def _stub_supabase_user(sb: MockSupabase, *, user_id: str, email: str) -> None:
    """Stub `supabase.auth.get_user(token)` to return the given user."""
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.user_metadata = {"full_name": "Alice Test"}
    user_response = MagicMock()
    user_response.user = user
    sb.auth.get_user.return_value = user_response


@pytest.mark.asyncio
class TestAutoProvisionerGate:
    async def test_blocks_when_pending_invite_exists(self):
        """Invitee hits the API for the first time without going through
        the invite callback — must be told to click the invite link, NOT
        get auto-provisioned a personal org."""
        invitee_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
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
            }
        )
        _stub_supabase_user(sb, user_id=invitee_id, email="alice@example.com")

        req = _make_request_with_token()
        with pytest.raises(HTTPException) as exc:
            await get_current_user(request=req, supabase=sb)
        assert exc.value.status_code == 409
        assert "pending invite" in exc.value.detail.lower()
        # And no personal org was created.
        assert "orgs" not in sb.store or not sb.store.get("orgs")

    async def test_passes_when_no_pending_invite(self):
        """Non-invited user: auto-provisioner fires, creates personal org."""
        user_id = str(uuid.uuid4())
        sb = MockSupabase({"org_members": [], "org_invites": []})
        _stub_supabase_user(sb, user_id=user_id, email="solo@example.com")

        req = _make_request_with_token()
        result = await get_current_user(request=req, supabase=sb)
        # Personal workspace created with role='owner'.
        assert result.role == "owner"
        # users + orgs + org_members all populated.
        assert sb.store.get("users")
        assert sb.store.get("orgs")
        assert sb.store.get("org_members")

    async def test_passes_when_user_already_has_membership(self):
        """Existing active member: no gate, no re-provision, just resolve."""
        user_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_members": [
                    {"id": str(uuid.uuid4()), "user_id": user_id, "org_id": org_id, "role": "limited"},
                ],
                "org_invites": [],
            }
        )
        _stub_supabase_user(sb, user_id=user_id, email="alice@example.com")

        req = _make_request_with_token()
        result = await get_current_user(request=req, supabase=sb)
        assert result.org_id == org_id
        assert result.role == "limited"

    async def test_pending_invite_check_is_case_insensitive(self):
        """Mixed-case email in the JWT must still match the lowercased
        email stored in org_invites."""
        invitee_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": str(uuid.uuid4()),
                        "org_id": str(uuid.uuid4()),
                        "email": "alice@example.com",  # lowercase as stored
                        "accepted_at": None,
                        "revoked_at": None,
                    }
                ],
                "org_members": [],
            }
        )
        _stub_supabase_user(sb, user_id=invitee_id, email="ALICE@Example.COM")

        req = _make_request_with_token()
        with pytest.raises(HTTPException) as exc:
            await get_current_user(request=req, supabase=sb)
        assert exc.value.status_code == 409
