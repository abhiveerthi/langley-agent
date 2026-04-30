"""
Workspace statuses endpoint — `GET /workspace/statuses` fallback paths and
`PUT /workspace/statuses` validation + persistence.

Same pattern as `test_brand_manager_router.py`: handlers called directly
with constructed `CurrentUser` + `MockSupabase` deps. No FastAPI
TestClient since auth is exercised orthogonally.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.dependencies import CurrentUser
from app.routers.tasks import (
    UpdateStatusesRequest,
    list_statuses,
    update_statuses,
    _DEFAULT_TASK_STATUSES,
    _MAX_STATUSES,
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
    def __init__(self, table_name: str, store: dict):
        self._table = table_name
        self._store = store
        self._filters: dict[str, str] = {}
        self._mode: str = "select"
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

    def limit(self, *_a, **_k): return self

    def execute(self):
        rows = self._store.get(self._table, [])
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


# ── GET /workspace/statuses fallback paths ────────────────────────────────
@pytest.mark.asyncio
class TestListStatuses:
    async def test_returns_org_custom_list(self, user: CurrentUser, real_uuid: str):
        sb = MockSupabase({
            "orgs": [{"id": real_uuid, "task_statuses": ["inbox", "doing", "qa", "shipped"]}],
        })
        result = await list_statuses(user=user, supabase=sb)
        assert result["statuses"] == ["inbox", "doing", "qa", "shipped"]

    async def test_falls_back_to_default_when_org_missing_column(self, user: CurrentUser, real_uuid: str):
        """Pre-migration env: org row exists but has no `task_statuses`
        column. Must not blow up — return the standard column set."""
        sb = MockSupabase({"orgs": [{"id": real_uuid}]})
        result = await list_statuses(user=user, supabase=sb)
        assert result["statuses"] == _DEFAULT_TASK_STATUSES

    async def test_falls_back_to_default_when_org_row_missing(self, user: CurrentUser):
        """Defensive: even a valid auth user could get here with the org
        row deleted (cascade race); fallback keeps the Kanban renderable."""
        sb = MockSupabase({"orgs": []})
        result = await list_statuses(user=user, supabase=sb)
        assert result["statuses"] == _DEFAULT_TASK_STATUSES

    async def test_falls_back_to_default_when_statuses_is_empty_list(self, user: CurrentUser, real_uuid: str):
        sb = MockSupabase({"orgs": [{"id": real_uuid, "task_statuses": []}]})
        result = await list_statuses(user=user, supabase=sb)
        assert result["statuses"] == _DEFAULT_TASK_STATUSES


# ── PUT /workspace/statuses persistence ───────────────────────────────────
@pytest.mark.asyncio
class TestUpdateStatuses:
    async def test_persists_new_list(self, user: CurrentUser, real_uuid: str):
        store = {"orgs": [{"id": real_uuid, "task_statuses": _DEFAULT_TASK_STATUSES.copy()}]}
        sb = MockSupabase(store)

        result = await update_statuses(
            body=UpdateStatusesRequest(statuses=["inbox", "doing", "shipped"]),
            user=user,
            supabase=sb,
        )
        assert result["statuses"] == ["inbox", "doing", "shipped"]
        # Underlying row mutated, not just the returned dict.
        assert store["orgs"][0]["task_statuses"] == ["inbox", "doing", "shipped"]

    async def test_404_when_org_not_found(self, user: CurrentUser):
        sb = MockSupabase({"orgs": []})
        with pytest.raises(HTTPException) as exc:
            await update_statuses(
                body=UpdateStatusesRequest(statuses=["todo"]),
                user=user,
                supabase=sb,
            )
        assert exc.value.status_code == 404

    async def test_org_scoped_update_skips_other_org(self, user: CurrentUser):
        """The eq("id", user.org_id) filter must scope the update — a
        different-org row should remain untouched."""
        other_org = str(uuid.uuid4())
        store = {
            "orgs": [
                {"id": other_org, "task_statuses": ["original"]},
            ],
        }
        sb = MockSupabase(store)
        with pytest.raises(HTTPException) as exc:
            await update_statuses(
                body=UpdateStatusesRequest(statuses=["new"]),
                user=user,
                supabase=sb,
            )
        assert exc.value.status_code == 404
        # Other org's row not mutated.
        assert store["orgs"][0]["task_statuses"] == ["original"]


# ── Validation rules (regex + dedup + length bounds) ──────────────────────
@pytest.mark.asyncio
class TestStatusValidation:
    async def test_rejects_uppercase(self, user: CurrentUser, real_uuid: str):
        sb = MockSupabase({"orgs": [{"id": real_uuid, "task_statuses": ["todo"]}]})
        with pytest.raises(HTTPException) as exc:
            await update_statuses(
                body=UpdateStatusesRequest(statuses=["ToDo"]),
                user=user,
                supabase=sb,
            )
        assert exc.value.status_code == 422
        assert "Invalid status" in exc.value.detail

    async def test_rejects_special_chars(self, user: CurrentUser, real_uuid: str):
        sb = MockSupabase({"orgs": [{"id": real_uuid, "task_statuses": ["todo"]}]})
        for bad in ["needs-review", "in progress", "done!", "qa/review"]:
            with pytest.raises(HTTPException) as exc:
                await update_statuses(
                    body=UpdateStatusesRequest(statuses=[bad]),
                    user=user,
                    supabase=sb,
                )
            assert exc.value.status_code == 422

    async def test_rejects_duplicates(self, user: CurrentUser, real_uuid: str):
        sb = MockSupabase({"orgs": [{"id": real_uuid, "task_statuses": ["todo"]}]})
        with pytest.raises(HTTPException) as exc:
            await update_statuses(
                body=UpdateStatusesRequest(statuses=["todo", "doing", "todo"]),
                user=user,
                supabase=sb,
            )
        assert exc.value.status_code == 422
        assert "Duplicate status" in exc.value.detail

    async def test_strips_whitespace(self, user: CurrentUser, real_uuid: str):
        """Leading/trailing whitespace is forgiven (likely paste artifacts);
        the trimmed value must still match the regex or it 422s."""
        store = {"orgs": [{"id": real_uuid, "task_statuses": ["todo"]}]}
        sb = MockSupabase(store)
        result = await update_statuses(
            body=UpdateStatusesRequest(statuses=["  todo  ", "doing"]),
            user=user,
            supabase=sb,
        )
        assert result["statuses"] == ["todo", "doing"]


# ── Pydantic schema bounds (sync tests, no async marker) ──────────────────
class TestUpdateStatusesRequestSchema:
    def test_rejects_empty_array(self):
        """min_length=1 prevents the FE from saving zero columns and
        breaking the Kanban — a settings UI should never let this through,
        but the schema is the safety net."""
        with pytest.raises(Exception):  # pydantic.ValidationError
            UpdateStatusesRequest(statuses=[])

    def test_rejects_too_many(self):
        too_many = [f"col_{i}" for i in range(_MAX_STATUSES + 1)]
        with pytest.raises(Exception):
            UpdateStatusesRequest(statuses=too_many)
