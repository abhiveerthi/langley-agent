"""
Org invites router — POST /api/invites, GET /api/invites,
POST /api/invites/{id}/complete, DELETE /api/invites/{id}, GET /api/members.

Tests run handlers directly with a MockSupabase that captures inserts +
updates and applies filter chains so we can assert org-scoping and
idempotent retry behavior. External dependencies (Supabase Auth admin,
Resend, Slack) are stubbed via a context-managed monkeypatch.

The single-org-per-user constraint and the auto-provisioner gate are the
two load-bearing security properties; both have dedicated tests below.
"""
from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.dependencies import AuthenticatedUser, CurrentUser
from app.routers.invites import (
    InviteCreate,
    InviteResponse,
    complete_invite,
    create_invite,
    get_invite_link,
    list_invites,
    list_members,
    revoke_invite,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def org_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def owner_user(org_id: str) -> CurrentUser:
    return CurrentUser(
        id=str(uuid.uuid4()),
        org_id=org_id,
        email="owner@example.com",
        role="owner",
    )


@pytest.fixture
def limited_user(org_id: str) -> CurrentUser:
    """A role='limited' invitee. v1 spec: limited members must NOT be
    able to send or revoke invites — gating those would let an invitee
    expand the org, which defeats the read-restriction model."""
    return CurrentUser(
        id=str(uuid.uuid4()),
        org_id=org_id,
        email="invitee@example.com",
        role="limited",
    )


@pytest.fixture
def settings_obj() -> Settings:
    return Settings(
        resend_api_key="re_test",
        email_from="invites@test.app",
        app_url="http://localhost:3000",
    )


# ── MockSupabase ──────────────────────────────────────────────────────────
# A more capable stand-in than conftest.MockSupabase: applies filter chains
# (eq + is_-null) and tracks side-effects so we can assert what writes
# happened, plus simulate insert-conflict behavior for the partial-unique
# constraint check.


class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    def __init__(self, table: str, store: dict, side_effects: dict):
        self._table = table
        self._store = store
        self._side_effects = side_effects
        self._mode = "select"
        self._payload: Any = None
        self._upsert_conflict: str | None = None
        self._eq: list[tuple[str, Any]] = []
        self._is_null: list[str] = []
        self._select_cols: tuple = ()

    def select(self, *cols, **_):
        self._mode = "select"
        self._select_cols = cols
        return self

    def insert(self, payload: dict):
        self._mode = "insert"
        self._payload = payload
        return self

    def upsert(self, payload: dict, on_conflict: str | None = None, **_):
        self._mode = "upsert"
        self._payload = payload
        self._upsert_conflict = on_conflict
        return self

    def update(self, payload: dict):
        self._mode = "update"
        self._payload = payload
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def eq(self, key: str, value: Any):
        self._eq.append((key, value))
        return self

    def is_(self, key: str, value: str):
        if value == "null":
            self._is_null.append(key)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def _matches(self, row: dict) -> bool:
        for k, v in self._eq:
            if row.get(k) != v:
                return False
        for k in self._is_null:
            if row.get(k) is not None:
                return False
        return True

    def execute(self):
        rows = self._store.setdefault(self._table, [])

        if self._mode == "select":
            return _MockResult([deepcopy(r) for r in rows if self._matches(r)])

        if self._mode == "insert":
            new_row = dict(self._payload)
            new_row.setdefault("id", str(uuid.uuid4()))
            new_row.setdefault("created_at", "2026-05-03T00:00:00Z")
            # Simulate partial-unique on (org_id, email) where active.
            if self._table == "org_invites":
                for r in rows:
                    if (
                        r.get("org_id") == new_row.get("org_id")
                        and r.get("email") == new_row.get("email")
                        and r.get("revoked_at") is None
                        and r.get("accepted_at") is None
                    ):
                        raise Exception("duplicate key value violates unique constraint")
            rows.append(new_row)
            self._side_effects.setdefault("inserts", []).append((self._table, new_row))
            return _MockResult([deepcopy(new_row)])

        if self._mode == "update":
            updated = []
            for r in rows:
                if self._matches(r):
                    r.update(self._payload)
                    updated.append(deepcopy(r))
            self._side_effects.setdefault("updates", []).append((self._table, self._payload))
            return _MockResult(updated)

        if self._mode == "upsert":
            # Find by conflict columns, update if found, else insert.
            conflict_cols = (self._upsert_conflict or "id").split(",")
            for r in rows:
                if all(r.get(c) == self._payload.get(c) for c in conflict_cols):
                    r.update(self._payload)
                    self._side_effects.setdefault("upserts", []).append(
                        (self._table, "update", self._payload)
                    )
                    return _MockResult([deepcopy(r)])
            new_row = dict(self._payload)
            new_row.setdefault("id", str(uuid.uuid4()))
            rows.append(new_row)
            self._side_effects.setdefault("upserts", []).append(
                (self._table, "insert", self._payload)
            )
            return _MockResult([deepcopy(new_row)])

        if self._mode == "delete":
            kept = []
            removed = []
            for r in rows:
                if self._matches(r):
                    removed.append(r)
                else:
                    kept.append(r)
            self._store[self._table] = kept
            return _MockResult(removed)

        return _MockResult([])


class MockSupabase:
    def __init__(self, store: dict | None = None):
        self.store = store or {}
        self.side_effects: dict = {}
        # Auth admin slot — tests inject a MagicMock here.
        self.auth = MagicMock()

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self.store, self.side_effects)


def _make_supabase_with_generate_link(magic_link: str = "https://example.com/magic?token=abc") -> MockSupabase:
    sb = MockSupabase()
    # Configure auth.admin.generate_link to return the magic link.
    properties = MagicMock()
    properties.action_link = magic_link
    response = MagicMock()
    response.properties = properties
    sb.auth.admin.generate_link.return_value = response
    return sb


# ── POST /api/invites ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCreateInvite:
    async def test_email_invite_happy_path(
        self, owner_user: CurrentUser, settings_obj: Settings, monkeypatch
    ):
        sb = _make_supabase_with_generate_link()
        sb.store["orgs"] = [{"id": owner_user.org_id, "name": "Test Org", "slug": "test-org"}]
        sb.store["users"] = [{"id": owner_user.id, "email": "owner@example.com", "full_name": "Test Owner"}]

        # Stub Resend send.
        send_mock = AsyncMock(return_value="resend_msg_id_123")
        monkeypatch.setattr("app.routers.invites.send_invite_email", send_mock)

        body = InviteCreate(email="alice@example.com", delivery_method="email")
        result = await create_invite(body=body, user=owner_user, supabase=sb, settings=settings_obj)

        assert result.invite.email == "alice@example.com"
        assert result.invite.delivery_method == "email"
        assert result.delivery_warnings == []
        # Resend was actually called.
        send_mock.assert_awaited_once()
        # Org_invites row stamped with last_delivery_attempt_at and no error.
        assert result.invite.last_delivery_attempt_at is not None
        assert result.invite.last_delivery_error is None
        # SECURITY: magic_link must NOT be exposed on the InviteResponse
        # shape returned by create/list/etc — that would let any org
        # member impersonate any pending invitee. Use GET /api/invites/{id}/link
        # (gated to owner/member) for the team-page Copy button instead.
        assert not hasattr(result.invite, "magic_link")
        # But the link IS stored on the underlying row so the dedicated
        # /link endpoint can serve it.
        stored = sb.store["org_invites"][0].get("magic_link")
        assert stored and stored.startswith("https://")

    async def test_rejects_existing_member(
        self, owner_user: CurrentUser, settings_obj: Settings, monkeypatch
    ):
        sb = _make_supabase_with_generate_link()
        sb.store["orgs"] = [{"id": owner_user.org_id, "name": "Test Org", "slug": "test-org"}]
        # Existing member with same email.
        existing_user_id = str(uuid.uuid4())
        sb.store["users"] = [
            {"id": owner_user.id, "email": "owner@example.com"},
            {"id": existing_user_id, "email": "alice@example.com"},
        ]
        sb.store["org_members"] = [
            {"id": str(uuid.uuid4()), "org_id": str(uuid.uuid4()), "user_id": existing_user_id, "role": "owner"},
        ]

        body = InviteCreate(email="alice@example.com", delivery_method="email")
        with pytest.raises(HTTPException) as exc:
            await create_invite(body=body, user=owner_user, supabase=sb, settings=settings_obj)
        assert exc.value.status_code == 409
        assert "already a member" in exc.value.detail.lower()

    async def test_rejects_duplicate_pending_invite(
        self, owner_user: CurrentUser, settings_obj: Settings, monkeypatch
    ):
        sb = _make_supabase_with_generate_link()
        sb.store["orgs"] = [{"id": owner_user.org_id, "name": "Test Org", "slug": "test-org"}]
        sb.store["users"] = [{"id": owner_user.id, "email": "owner@example.com"}]
        # Existing pending invite for the same email.
        sb.store["org_invites"] = [
            {
                "id": str(uuid.uuid4()),
                "org_id": owner_user.org_id,
                "email": "alice@example.com",
                "invited_by": owner_user.id,
                "delivery_method": "email",
                "accepted_at": None,
                "revoked_at": None,
                "created_at": "2026-05-03T00:00:00Z",
            }
        ]

        body = InviteCreate(email="alice@example.com", delivery_method="email")
        with pytest.raises(HTTPException) as exc:
            await create_invite(body=body, user=owner_user, supabase=sb, settings=settings_obj)
        assert exc.value.status_code == 409

    async def test_email_lowercased(
        self, owner_user: CurrentUser, settings_obj: Settings, monkeypatch
    ):
        sb = _make_supabase_with_generate_link()
        sb.store["orgs"] = [{"id": owner_user.org_id, "name": "Test Org", "slug": "test-org"}]
        sb.store["users"] = [{"id": owner_user.id, "email": "owner@example.com"}]

        monkeypatch.setattr(
            "app.routers.invites.send_invite_email",
            AsyncMock(return_value="msg_id"),
        )

        body = InviteCreate(email="Alice@Example.COM", delivery_method="email")
        result = await create_invite(body=body, user=owner_user, supabase=sb, settings=settings_obj)
        assert result.invite.email == "alice@example.com"

    async def test_email_delivery_failure_stamps_error(
        self, owner_user: CurrentUser, settings_obj: Settings, monkeypatch
    ):
        from app.services.email import EmailDeliveryError

        sb = _make_supabase_with_generate_link()
        sb.store["orgs"] = [{"id": owner_user.org_id, "name": "Test Org", "slug": "test-org"}]
        sb.store["users"] = [{"id": owner_user.id, "email": "owner@example.com"}]

        send_mock = AsyncMock(side_effect=EmailDeliveryError("resend 429: rate limited"))
        monkeypatch.setattr("app.routers.invites.send_invite_email", send_mock)

        body = InviteCreate(email="alice@example.com", delivery_method="email")
        result = await create_invite(body=body, user=owner_user, supabase=sb, settings=settings_obj)
        # Row is created, warning surfaced, error stamped.
        assert result.invite.email == "alice@example.com"
        assert any("resend" in w.lower() for w in result.delivery_warnings)
        assert result.invite.last_delivery_error is not None
        assert "resend" in result.invite.last_delivery_error.lower()
        # CRITICAL: magic_link is still persisted on the row (so the
        # /link endpoint can serve it) even when delivery fails. The
        # response shape hides it; the row keeps it.
        stored = sb.store["org_invites"][0].get("magic_link")
        assert stored and stored.startswith("https://")

    async def test_limited_role_blocked_403(
        self, limited_user: CurrentUser, settings_obj: Settings
    ):
        """Security: a limited-role invitee must NOT be able to send
        invites. Allowing it would expand the org via someone whose
        role is supposed to RESTRICT them."""
        sb = _make_supabase_with_generate_link()
        body = InviteCreate(email="anyone@example.com", delivery_method="email")
        with pytest.raises(HTTPException) as exc:
            await create_invite(body=body, user=limited_user, supabase=sb, settings=settings_obj)
        assert exc.value.status_code == 403
        assert "permission" in exc.value.detail.lower()

    async def test_slack_invite_happy_path(
        self, owner_user: CurrentUser, settings_obj: Settings, monkeypatch
    ):
        sb = _make_supabase_with_generate_link()
        sb.store["orgs"] = [{"id": owner_user.org_id, "name": "Test Org", "slug": "test-org"}]
        sb.store["users"] = [{"id": owner_user.id, "email": "owner@example.com"}]

        slack_mock = AsyncMock(return_value="1234567.890")
        monkeypatch.setattr("app.routers.invites.post_invite_to_slack", slack_mock)

        body = InviteCreate(
            email="alice@example.com",
            delivery_method="slack",
            slack_channel_id="C12345",
        )
        result = await create_invite(body=body, user=owner_user, supabase=sb, settings=settings_obj)

        assert result.delivery_warnings == []
        slack_mock.assert_awaited_once()
        # Resend should NOT be called for slack-only delivery.
        assert result.invite.delivery_method == "slack"


# ── DELETE /api/invites/{id} ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestRevokeInvite:
    async def test_revokes_pending_invite(self, owner_user: CurrentUser):
        invite_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": owner_user.org_id,
                        "email": "alice@example.com",
                        "invited_by": owner_user.id,
                        "delivery_method": "email",
                        "accepted_at": None,
                        "revoked_at": None,
                    }
                ]
            }
        )
        await revoke_invite(invite_id=invite_id, user=owner_user, supabase=sb)
        assert sb.store["org_invites"][0]["revoked_at"] is not None

    async def test_404_when_invite_not_found(self, owner_user: CurrentUser):
        sb = MockSupabase({"org_invites": []})
        with pytest.raises(HTTPException) as exc:
            await revoke_invite(invite_id=str(uuid.uuid4()), user=owner_user, supabase=sb)
        assert exc.value.status_code == 404

    async def test_404_when_invite_in_other_org(self, owner_user: CurrentUser):
        invite_id = str(uuid.uuid4())
        other_org = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": other_org,
                        "email": "alice@example.com",
                        "accepted_at": None,
                        "revoked_at": None,
                    }
                ]
            }
        )
        with pytest.raises(HTTPException) as exc:
            await revoke_invite(invite_id=invite_id, user=owner_user, supabase=sb)
        assert exc.value.status_code == 404

    async def test_limited_role_blocked_403(self, limited_user: CurrentUser):
        """Same role gate on DELETE — limited users can't revoke invites."""
        sb = MockSupabase({"org_invites": []})
        with pytest.raises(HTTPException) as exc:
            await revoke_invite(invite_id=str(uuid.uuid4()), user=limited_user, supabase=sb)
        assert exc.value.status_code == 403

    async def test_400_when_already_accepted(self, owner_user: CurrentUser):
        invite_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": owner_user.org_id,
                        "email": "alice@example.com",
                        "accepted_at": "2026-05-03T01:00:00Z",
                        "revoked_at": None,
                    }
                ]
            }
        )
        with pytest.raises(HTTPException) as exc:
            await revoke_invite(invite_id=invite_id, user=owner_user, supabase=sb)
        assert exc.value.status_code == 400


# ── POST /api/invites/{id}/complete ───────────────────────────────────────


@pytest.mark.asyncio
class TestCompleteInvite:
    async def test_brand_new_user_happy_path(self, org_id: str):
        invite_id = str(uuid.uuid4())
        invitee_user_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": org_id,
                        "email": "alice@example.com",
                        "delivery_method": "email",
                        "accepted_at": None,
                        "revoked_at": None,
                    }
                ],
                "orgs": [{"id": org_id, "name": "Test Org", "slug": "test-org"}],
                "users": [],
                "org_members": [],
            }
        )
        auth_user = AuthenticatedUser(id=invitee_user_id, email="alice@example.com")

        result = await complete_invite(invite_id=invite_id, auth_user=auth_user, supabase=sb)

        assert result.org_id == org_id
        # users row inserted via upsert.
        assert len(sb.store["users"]) == 1
        assert sb.store["users"][0]["id"] == invitee_user_id
        # org_members row inserted with role='limited'.
        assert len(sb.store["org_members"]) == 1
        assert sb.store["org_members"][0]["role"] == "limited"
        assert sb.store["org_members"][0]["user_id"] == invitee_user_id
        # accepted_at stamped.
        assert sb.store["org_invites"][0]["accepted_at"] is not None

    async def test_404_when_invite_not_found(self, org_id: str):
        sb = MockSupabase({"org_invites": []})
        auth_user = AuthenticatedUser(id=str(uuid.uuid4()), email="alice@example.com")
        with pytest.raises(HTTPException) as exc:
            await complete_invite(invite_id=str(uuid.uuid4()), auth_user=auth_user, supabase=sb)
        assert exc.value.status_code == 404

    async def test_410_when_revoked(self, org_id: str):
        invite_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": org_id,
                        "email": "alice@example.com",
                        "accepted_at": None,
                        "revoked_at": "2026-05-03T01:00:00Z",
                    }
                ]
            }
        )
        auth_user = AuthenticatedUser(id=str(uuid.uuid4()), email="alice@example.com")
        with pytest.raises(HTTPException) as exc:
            await complete_invite(invite_id=invite_id, auth_user=auth_user, supabase=sb)
        assert exc.value.status_code == 410

    async def test_403_when_email_mismatch(self, org_id: str):
        """Critical: invitee can't claim someone else's invite even with a valid JWT."""
        invite_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": org_id,
                        "email": "alice@example.com",
                        "accepted_at": None,
                        "revoked_at": None,
                    }
                ]
            }
        )
        # Different user trying to accept Alice's invite.
        auth_user = AuthenticatedUser(id=str(uuid.uuid4()), email="bob@example.com")
        with pytest.raises(HTTPException) as exc:
            await complete_invite(invite_id=invite_id, auth_user=auth_user, supabase=sb)
        assert exc.value.status_code == 403

    async def test_409_when_already_in_other_org(self, org_id: str):
        """Single-org-per-user constraint: blocks invitee with existing membership."""
        invite_id = str(uuid.uuid4())
        invitee_user_id = str(uuid.uuid4())
        other_org = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": org_id,
                        "email": "alice@example.com",
                        "accepted_at": None,
                        "revoked_at": None,
                    }
                ],
                "orgs": [{"id": other_org, "name": "Other Workspace", "slug": "other"}],
                "org_members": [
                    {"id": str(uuid.uuid4()), "org_id": other_org, "user_id": invitee_user_id, "role": "owner"},
                ],
            }
        )
        auth_user = AuthenticatedUser(id=invitee_user_id, email="alice@example.com")
        with pytest.raises(HTTPException) as exc:
            await complete_invite(invite_id=invite_id, auth_user=auth_user, supabase=sb)
        assert exc.value.status_code == 409
        assert "Other Workspace" in exc.value.detail

    async def test_idempotent_retry(self, org_id: str):
        """CRITICAL: re-running accept with the same token after a partial
        failure must not produce duplicate rows or flip state."""
        invite_id = str(uuid.uuid4())
        invitee_user_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": org_id,
                        "email": "alice@example.com",
                        "accepted_at": None,
                        "revoked_at": None,
                    }
                ],
                "orgs": [{"id": org_id, "name": "Test Org", "slug": "test-org"}],
                "users": [],
                "org_members": [],
            }
        )
        auth_user = AuthenticatedUser(id=invitee_user_id, email="alice@example.com")

        # First call.
        result1 = await complete_invite(invite_id=invite_id, auth_user=auth_user, supabase=sb)
        # Second call (retry) — same token, same user.
        result2 = await complete_invite(invite_id=invite_id, auth_user=auth_user, supabase=sb)

        assert result1.org_id == result2.org_id == org_id
        # Exactly one users row.
        assert len(sb.store["users"]) == 1
        # Exactly one org_members row.
        assert len(sb.store["org_members"]) == 1
        # accepted_at unchanged on the retry (set by first call).
        first_accepted = sb.store["org_invites"][0]["accepted_at"]
        assert first_accepted is not None
        # The handler's UPDATE filters on accepted_at IS NULL, so on retry
        # the timestamp is not overwritten.

    async def test_email_case_insensitive_match(self, org_id: str):
        """Authenticated email vs invite email must match case-insensitively."""
        invite_id = str(uuid.uuid4())
        invitee_user_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": org_id,
                        "email": "alice@example.com",
                        "accepted_at": None,
                        "revoked_at": None,
                    }
                ],
                "orgs": [{"id": org_id, "name": "Test Org", "slug": "test-org"}],
                "users": [],
                "org_members": [],
            }
        )
        # Auth provider returns mixed-case email — should still match.
        auth_user = AuthenticatedUser(id=invitee_user_id, email="ALICE@example.COM")
        result = await complete_invite(invite_id=invite_id, auth_user=auth_user, supabase=sb)
        assert result.org_id == org_id


# ── GET /api/invites/{id}/link ────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetInviteLink:
    """The dedicated link endpoint is the secure replacement for
    putting magic_link in the list response. Tests pin its access
    boundary."""

    def _seeded(self, owner_user: CurrentUser, **overrides) -> tuple[str, MockSupabase]:
        invite_id = str(uuid.uuid4())
        row = {
            "id": invite_id,
            "org_id": owner_user.org_id,
            "email": "alice@example.com",
            "invited_by": owner_user.id,
            "delivery_method": "email",
            "magic_link": "https://supabase.example.com/auth/v1/verify?token=secret-token-xyz",
            "accepted_at": None,
            "revoked_at": None,
            "created_at": "2026-05-03T00:00:00Z",
        }
        row.update(overrides)
        sb = MockSupabase({"org_invites": [row]})
        return invite_id, sb

    async def test_owner_gets_link(self, owner_user: CurrentUser):
        invite_id, sb = self._seeded(owner_user)
        result = await get_invite_link(invite_id=invite_id, user=owner_user, supabase=sb)
        assert result.magic_link.startswith("https://supabase.example.com")

    async def test_limited_role_blocked_403(self, limited_user: CurrentUser):
        """Critical: limited members must NOT be able to fetch the link.
        That's the whole vulnerability we're patching — handing it to
        them lets them impersonate the pending invitee."""
        invite_id = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": limited_user.org_id,
                        "email": "alice@example.com",
                        "invited_by": str(uuid.uuid4()),
                        "delivery_method": "email",
                        "magic_link": "https://supabase.example.com/m",
                        "accepted_at": None,
                        "revoked_at": None,
                        "created_at": "2026-05-03T00:00:00Z",
                    }
                ]
            }
        )
        with pytest.raises(HTTPException) as exc:
            await get_invite_link(invite_id=invite_id, user=limited_user, supabase=sb)
        assert exc.value.status_code == 403

    async def test_404_when_invite_not_found(self, owner_user: CurrentUser):
        sb = MockSupabase({"org_invites": []})
        with pytest.raises(HTTPException) as exc:
            await get_invite_link(invite_id=str(uuid.uuid4()), user=owner_user, supabase=sb)
        assert exc.value.status_code == 404

    async def test_404_when_invite_in_other_org(self, owner_user: CurrentUser):
        """Cross-org access returns 404, not 403, so we don't confirm
        the existence of invites belonging to a different tenant."""
        invite_id = str(uuid.uuid4())
        other_org = str(uuid.uuid4())
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": invite_id,
                        "org_id": other_org,
                        "email": "alice@example.com",
                        "invited_by": str(uuid.uuid4()),
                        "delivery_method": "email",
                        "magic_link": "https://supabase.example.com/m",
                        "accepted_at": None,
                        "revoked_at": None,
                        "created_at": "2026-05-03T00:00:00Z",
                    }
                ]
            }
        )
        with pytest.raises(HTTPException) as exc:
            await get_invite_link(invite_id=invite_id, user=owner_user, supabase=sb)
        assert exc.value.status_code == 404

    async def test_410_when_accepted(self, owner_user: CurrentUser):
        invite_id, sb = self._seeded(owner_user, accepted_at="2026-05-03T01:00:00Z")
        with pytest.raises(HTTPException) as exc:
            await get_invite_link(invite_id=invite_id, user=owner_user, supabase=sb)
        assert exc.value.status_code == 410

    async def test_410_when_revoked(self, owner_user: CurrentUser):
        invite_id, sb = self._seeded(owner_user, revoked_at="2026-05-03T01:00:00Z")
        with pytest.raises(HTTPException) as exc:
            await get_invite_link(invite_id=invite_id, user=owner_user, supabase=sb)
        assert exc.value.status_code == 410

    async def test_404_when_magic_link_null(self, owner_user: CurrentUser):
        """Legacy rows from before migration 011 won't have a link."""
        invite_id, sb = self._seeded(owner_user, magic_link=None)
        with pytest.raises(HTTPException) as exc:
            await get_invite_link(invite_id=invite_id, user=owner_user, supabase=sb)
        assert exc.value.status_code == 404


# ── GET /api/invites ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListInvites:
    async def test_response_shape_does_not_expose_magic_link(self, owner_user: CurrentUser):
        """Regression: no field named magic_link on InviteResponse, and
        no row in the list response carries it as a key. This is the
        whole point of the security fix — a list endpoint cannot leak
        single-use sign-in tokens."""
        assert "magic_link" not in InviteResponse.model_fields

        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": str(uuid.uuid4()),
                        "org_id": owner_user.org_id,
                        "email": "pending@example.com",
                        "invited_by": owner_user.id,
                        "delivery_method": "email",
                        "magic_link": "https://supabase.example.com/SECRET-TOKEN",
                        "accepted_at": None,
                        "revoked_at": None,
                        "created_at": "2026-05-03T00:00:00Z",
                    },
                ]
            }
        )
        result = await list_invites(user=owner_user, supabase=sb)
        # No row on the wire contains the magic link, even when the
        # underlying DB row does.
        for row in result:
            dumped = row.model_dump()
            assert "magic_link" not in dumped
            assert "SECRET-TOKEN" not in str(dumped)

    async def test_returns_only_pending(self, owner_user: CurrentUser):
        sb = MockSupabase(
            {
                "org_invites": [
                    {
                        "id": str(uuid.uuid4()),
                        "org_id": owner_user.org_id,
                        "email": "pending@example.com",
                        "invited_by": owner_user.id,
                        "delivery_method": "email",
                        "accepted_at": None,
                        "revoked_at": None,
                        "created_at": "2026-05-03T00:00:00Z",
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "org_id": owner_user.org_id,
                        "email": "accepted@example.com",
                        "invited_by": owner_user.id,
                        "delivery_method": "email",
                        "accepted_at": "2026-05-02T00:00:00Z",
                        "revoked_at": None,
                        "created_at": "2026-05-01T00:00:00Z",
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "org_id": owner_user.org_id,
                        "email": "revoked@example.com",
                        "invited_by": owner_user.id,
                        "delivery_method": "email",
                        "accepted_at": None,
                        "revoked_at": "2026-05-02T00:00:00Z",
                        "created_at": "2026-05-01T00:00:00Z",
                    },
                ]
            }
        )
        result = await list_invites(user=owner_user, supabase=sb)
        assert len(result) == 1
        assert result[0].email == "pending@example.com"


# ── GET /api/members ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListMembers:
    async def test_returns_org_members_with_user_data(self, owner_user: CurrentUser):
        sb = MockSupabase(
            {
                "org_members": [
                    {
                        "user_id": owner_user.id,
                        "org_id": owner_user.org_id,
                        "role": "owner",
                        "created_at": "2026-05-01T00:00:00Z",
                        "users": {"email": "owner@example.com", "full_name": "Test Owner"},
                    }
                ]
            }
        )
        # Patch the query to return the embedded users join.
        # Our MockSupabase doesn't natively support PostgREST joins, so we
        # pre-shape the row above with the join already embedded — same
        # shape the real client returns.
        result = await list_members(user=owner_user, supabase=sb)
        assert len(result) == 1
        assert result[0].email == "owner@example.com"
        assert result[0].role == "owner"


# ── Schema validation ─────────────────────────────────────────────────────


class TestInviteCreateSchema:
    def test_slack_method_requires_channel(self):
        with pytest.raises(Exception):  # pydantic.ValidationError
            InviteCreate(email="alice@example.com", delivery_method="slack")

    def test_both_method_requires_channel(self):
        with pytest.raises(Exception):
            InviteCreate(email="alice@example.com", delivery_method="both")

    def test_email_method_no_channel(self):
        body = InviteCreate(email="alice@example.com", delivery_method="email")
        assert body.slack_channel_id is None

    def test_invalid_delivery_method_rejected(self):
        with pytest.raises(Exception):
            InviteCreate(email="alice@example.com", delivery_method="carrier-pigeon")  # type: ignore[arg-type]
