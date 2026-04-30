"""
Brand Manager router endpoints — `GET /deals/{id}` and `PATCH /deals/{id}`.

The handlers are async functions wrapped by `Depends(get_current_user, get_supabase)`,
but they're plain callables when invoked directly with the deps satisfied.
That sidesteps the need to spin up TestClient + mock the auth header path —
the auth dep is exercised separately and orthogonally to this router.

Mocks: same `MockSupabase` shape as the other tests so we can capture
selects, updates, and the org-scoping `.eq("org_id", ...)` filter.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.dependencies import CurrentUser
from app.routers.brand_manager import (
    UpdateDealRequest,
    get_deal,
    list_deals,
    update_deal,
)


@pytest.fixture
def real_uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def user(real_uuid: str) -> CurrentUser:
    return CurrentUser(
        id=str(uuid.uuid4()),
        org_id=real_uuid,
        email="creator@example.com",
        role="member",
    )


# ── Mock Supabase capturing query state ───────────────────────────────────
class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    """Captures the chain of select/eq/order/limit/update calls so tests
    can assert which filters and updates were applied."""
    def __init__(self, table_name: str, store: dict):
        self._table = table_name
        self._store = store
        self._filters: dict[str, str] = {}
        self._mode: str = "select"  # select | update
        self._update_payload: dict | None = None

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def update(self, payload: dict):
        self._mode = "update"
        self._update_payload = payload
        return self

    def eq(self, key: str, value):
        self._filters[key] = value
        return self

    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def execute(self):
        rows = self._store.get(self._table, [])
        # Apply filters — naive equality match, fine for tests.
        matching = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
        if self._mode == "update" and self._update_payload is not None:
            for r in matching:
                r.update(self._update_payload)
            return _MockResult(matching)
        return _MockResult(matching)


class MockSupabase:
    def __init__(self, store: dict | None = None):
        self._store = store or {}

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._store)


# ── Handler tests ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestListDeals:
    async def test_returns_org_scoped_deals(self, user: CurrentUser, real_uuid: str):
        other_org = str(uuid.uuid4())
        store = {
            "brand_deals": [
                {"id": str(uuid.uuid4()), "org_id": real_uuid, "brand_name": "Magpul"},
                {"id": str(uuid.uuid4()), "org_id": real_uuid, "brand_name": "Holosun"},
                # Different org — must NOT come back.
                {"id": str(uuid.uuid4()), "org_id": other_org, "brand_name": "Glock"},
            ],
        }
        sb = MockSupabase(store)
        result = await list_deals(limit=50, user=user, supabase=sb)
        assert len(result) == 2
        assert {d["brand_name"] for d in result} == {"Magpul", "Holosun"}


@pytest.mark.asyncio
class TestGetDeal:
    async def test_returns_deal_and_linked_tasks(self, user: CurrentUser, real_uuid: str):
        deal_id = str(uuid.uuid4())
        store = {
            "brand_deals": [
                {"id": deal_id, "org_id": real_uuid, "brand_name": "Magpul",
                 "stage": "pitched", "subject": "Sponsor opp", "recipient": "m@magpul.com",
                 "notes": None},
            ],
            "tasks": [
                {"id": str(uuid.uuid4()), "org_id": real_uuid, "deal_id": deal_id,
                 "title": "Follow up with Magpul", "status": "todo", "priority": "medium"},
                # Task on a different deal — must NOT come back.
                {"id": str(uuid.uuid4()), "org_id": real_uuid, "deal_id": str(uuid.uuid4()),
                 "title": "Follow up with Holosun", "status": "todo", "priority": "medium"},
                # Task on the right deal but different org — must NOT come back.
                {"id": str(uuid.uuid4()), "org_id": str(uuid.uuid4()), "deal_id": deal_id,
                 "title": "Other-org task", "status": "todo", "priority": "medium"},
            ],
        }
        sb = MockSupabase(store)
        result = await get_deal(deal_id=deal_id, user=user, supabase=sb)
        assert result["deal"]["brand_name"] == "Magpul"
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["title"] == "Follow up with Magpul"

    async def test_404_when_deal_not_found(self, user: CurrentUser):
        sb = MockSupabase({"brand_deals": [], "tasks": []})
        with pytest.raises(HTTPException) as exc:
            await get_deal(deal_id=str(uuid.uuid4()), user=user, supabase=sb)
        assert exc.value.status_code == 404

    async def test_404_when_deal_belongs_to_other_org(self, user: CurrentUser):
        """Catches the most important security property — the org filter
        prevents cross-tenant reads even if the FE sends a deal_id that
        exists in a different org."""
        deal_id = str(uuid.uuid4())
        other_org = str(uuid.uuid4())
        sb = MockSupabase({
            "brand_deals": [{"id": deal_id, "org_id": other_org, "brand_name": "X"}],
            "tasks": [],
        })
        with pytest.raises(HTTPException) as exc:
            await get_deal(deal_id=deal_id, user=user, supabase=sb)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
class TestUpdateDeal:
    async def test_stage_change_updates_row(self, user: CurrentUser, real_uuid: str):
        deal_id = str(uuid.uuid4())
        store = {
            "brand_deals": [
                {"id": deal_id, "org_id": real_uuid, "brand_name": "Magpul", "stage": "pitched"},
            ],
        }
        sb = MockSupabase(store)
        result = await update_deal(
            deal_id=deal_id,
            body=UpdateDealRequest(stage="negotiating"),
            user=user,
            supabase=sb,
        )
        assert result["stage"] == "negotiating"
        # And the underlying row was actually mutated, not just shadowed.
        assert store["brand_deals"][0]["stage"] == "negotiating"

    async def test_notes_update_alone_works(self, user: CurrentUser, real_uuid: str):
        """Notes are a free-text annotation field — independent of stage."""
        deal_id = str(uuid.uuid4())
        store = {
            "brand_deals": [
                {"id": deal_id, "org_id": real_uuid, "brand_name": "Magpul",
                 "stage": "pitched", "notes": None},
            ],
        }
        sb = MockSupabase(store)
        result = await update_deal(
            deal_id=deal_id,
            body=UpdateDealRequest(notes="Left voicemail Tuesday"),
            user=user,
            supabase=sb,
        )
        assert result["notes"] == "Left voicemail Tuesday"
        # Stage untouched.
        assert result["stage"] == "pitched"

    async def test_400_when_payload_empty(self, user: CurrentUser, real_uuid: str):
        """An empty PATCH would be a no-op; surface it as 400 so the FE's
        bug is visible rather than masked as a 200."""
        deal_id = str(uuid.uuid4())
        sb = MockSupabase({
            "brand_deals": [{"id": deal_id, "org_id": real_uuid, "stage": "pitched"}],
        })
        with pytest.raises(HTTPException) as exc:
            await update_deal(
                deal_id=deal_id,
                body=UpdateDealRequest(),  # nothing set
                user=user,
                supabase=sb,
            )
        assert exc.value.status_code == 400

    async def test_404_when_deal_not_in_org(self, user: CurrentUser):
        deal_id = str(uuid.uuid4())
        other_org = str(uuid.uuid4())
        sb = MockSupabase({
            "brand_deals": [{"id": deal_id, "org_id": other_org, "stage": "pitched"}],
        })
        with pytest.raises(HTTPException) as exc:
            await update_deal(
                deal_id=deal_id,
                body=UpdateDealRequest(stage="signed"),
                user=user,
                supabase=sb,
            )
        assert exc.value.status_code == 404


# ── Pydantic schema validation ────────────────────────────────────────────
class TestUpdateDealRequestSchema:
    def test_accepts_valid_stage_literal(self):
        body = UpdateDealRequest(stage="negotiating")
        assert body.stage == "negotiating"

    def test_rejects_invalid_stage(self):
        """The Literal type guards against typos / made-up stages before
        they hit the DB CHECK constraint — Pydantic raises ValidationError."""
        with pytest.raises(Exception):  # pydantic.ValidationError
            UpdateDealRequest(stage="ghosted")  # type: ignore[arg-type]

    def test_both_fields_optional(self):
        body = UpdateDealRequest()
        assert body.stage is None
        assert body.notes is None
