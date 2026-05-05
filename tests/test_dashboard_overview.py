"""
Dashboard overview endpoint — `GET /api/dashboard/overview`.

Returns the combined feed for `/app/agents` (recent runs + pending
approvals) in a single round trip. This file exercises:
  - the response shape
  - org-scoping on both halves (cross-tenant rows must NOT leak)
  - the `runs_limit` query param actually trims the runs list
  - the approvals filter (status=pending) excludes already-handled rows

Same handler-direct pattern as the other router tests — `CurrentUser`
+ `MockSupabase` plumbed in directly, no FastAPI TestClient.
"""
from __future__ import annotations

import uuid

import pytest

from app.dependencies import CurrentUser
from app.routers.dashboard import get_overview


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


# ── Mock Supabase (shared shape with test_brand_manager_router.py) ────────
class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    def __init__(self, table_name: str, store: dict):
        self._table = table_name
        self._store = store
        self._filters: dict[str, str] = {}
        self._limit: int | None = None

    def select(self, *_a, **_k): return self
    def eq(self, key: str, value):
        self._filters[key] = value
        return self
    def order(self, *_a, **_k): return self

    def limit(self, n: int, *_a, **_k):
        self._limit = n
        return self

    def execute(self):
        rows = self._store.get(self._table, [])
        matching = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
        if self._limit is not None:
            matching = matching[:self._limit]
        return _MockResult(matching)


class MockSupabase:
    def __init__(self, store: dict | None = None):
        self._store = store or {}

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._store)


# ── Tests ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
class TestGetOverview:
    async def test_returns_runs_and_pending_approvals(self, user: CurrentUser, real_uuid: str):
        store = {
            "agent_runs": [
                {"id": str(uuid.uuid4()), "org_id": real_uuid,
                 "status": "completed", "started_at": "2026-05-04T00:00:00Z"},
                {"id": str(uuid.uuid4()), "org_id": real_uuid,
                 "status": "running", "started_at": "2026-05-03T00:00:00Z"},
            ],
            "approvals": [
                # Pending — included.
                {"id": str(uuid.uuid4()), "org_id": real_uuid,
                 "status": "pending", "action_type": "send_email",
                 "created_at": "2026-05-04T12:00:00Z"},
                # Approved — excluded.
                {"id": str(uuid.uuid4()), "org_id": real_uuid,
                 "status": "approved", "action_type": "send_email",
                 "created_at": "2026-05-03T12:00:00Z"},
            ],
        }
        sb = MockSupabase(store)
        result = await get_overview(runs_limit=8, user=user, supabase=sb)
        assert len(result["runs"]) == 2
        assert len(result["pending_approvals"]) == 1
        assert result["pending_approvals"][0]["status"] == "pending"

    async def test_runs_limit_trims_response(self, user: CurrentUser, real_uuid: str):
        """Default limit is 8; the FE used to slice client-side after
        pulling everything. Confirm the server-side limit actually fires."""
        store = {
            "agent_runs": [
                {"id": str(uuid.uuid4()), "org_id": real_uuid, "status": "completed",
                 "started_at": f"2026-05-{i:02d}T00:00:00Z"}
                for i in range(1, 21)  # 20 runs
            ],
            "approvals": [],
        }
        sb = MockSupabase(store)
        result = await get_overview(runs_limit=5, user=user, supabase=sb)
        assert len(result["runs"]) == 5

    async def test_org_scoped(self, user: CurrentUser, real_uuid: str):
        """Both halves must filter on org_id — a leaked token from
        another tenant should otherwise see their runs and approvals."""
        other_org = str(uuid.uuid4())
        store = {
            "agent_runs": [
                {"id": str(uuid.uuid4()), "org_id": real_uuid,
                 "status": "completed", "started_at": "2026-05-04T00:00:00Z"},
                {"id": str(uuid.uuid4()), "org_id": other_org,
                 "status": "completed", "started_at": "2026-05-04T00:00:00Z"},
            ],
            "approvals": [
                {"id": str(uuid.uuid4()), "org_id": real_uuid,
                 "status": "pending", "action_type": "x",
                 "created_at": "2026-05-04T00:00:00Z"},
                {"id": str(uuid.uuid4()), "org_id": other_org,
                 "status": "pending", "action_type": "x",
                 "created_at": "2026-05-04T00:00:00Z"},
            ],
        }
        sb = MockSupabase(store)
        result = await get_overview(runs_limit=8, user=user, supabase=sb)
        assert len(result["runs"]) == 1
        assert result["runs"][0]["org_id"] == real_uuid
        assert len(result["pending_approvals"]) == 1
        assert result["pending_approvals"][0]["org_id"] == real_uuid

    async def test_empty_state(self, user: CurrentUser):
        sb = MockSupabase({"agent_runs": [], "approvals": []})
        result = await get_overview(runs_limit=8, user=user, supabase=sb)
        assert result["runs"] == []
        assert result["pending_approvals"] == []
