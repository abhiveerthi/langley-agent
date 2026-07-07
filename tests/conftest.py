"""
Shared pytest fixtures.

Test design rules baked in here:
  - No real LLM calls. Tests run in <5 seconds, no API keys required.
  - No real Postgres / Supabase. `mock_supabase` is the hand-rolled stand-in.
  - No live ContextVars leaking between tests. `_reset_contextvars` is autouse.

If a test needs real model output for evaluation, that lives outside this
suite (e.g. `scripts/run_agent.py` which talks to live Anthropic).
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from packages.agents.core.profile import OrgProfile, load_profile
from packages.integrations.context import (
    current_org_id,
    current_supabase,
    current_user_id,
)


# ── ContextVar hygiene ────────────────────────────────────────────────────
# The agent runtime sets these per-request (via app.auth.with_tool_context).
# In tests, fixtures or earlier tests can leave values lying around — this
# autouse fixture wipes them before every test so order-of-execution can't
# cause flake.
@pytest.fixture(autouse=True)
def _reset_contextvars():
    current_org_id.set(None)
    current_user_id.set(None)
    current_supabase.set(None)
    yield


# ── Live-key hygiene ──────────────────────────────────────────────────────
# The Content Agent's integrations gate on env keys via is_configured().
# A dev shell with a real key exported (or loaded into os.environ by
# app.main's load_dotenv when another test imports it) would flip those
# gates ON and send tests to the LIVE Riverside/Opus APIs. Scrub them for
# every test; a test that wants the configured path monkeypatches
# is_configured (or setenv) explicitly.
@pytest.fixture(autouse=True)
def _scrub_content_integration_keys(monkeypatch):
    monkeypatch.delenv("RIVERSIDE_API_KEY", raising=False)
    monkeypatch.delenv("OPUSCLIP_API_KEY", raising=False)


# ── Mock Supabase client ──────────────────────────────────────────────────
class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    """Mimics the chained query builder. All filter/order/limit calls are
    no-ops that return self; `execute()` returns whatever rows the parent
    MockSupabase has registered for this table name."""

    def __init__(self, table_name: str, canned: dict):
        self._table = table_name
        self._canned = canned

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def insert(self, payload):
        self._canned.setdefault("_inserts", []).append((self._table, payload))
        return self
    def upsert(self, payload, **_k):
        self._canned.setdefault("_upserts", []).append((self._table, payload))
        return self
    def update(self, payload):
        self._canned.setdefault("_updates", []).append((self._table, payload))
        return self
    def delete(self): return self

    def execute(self):
        return _MockResult(self._canned.get(self._table, []))


class MockSupabase:
    """Process-local Supabase stand-in.

    Construct with a dict mapping table-name → list of canned row dicts.
    `_inserts` / `_upserts` / `_updates` keys are auto-populated when those
    methods are called, so tests can assert on what writes the agent issued.

        sb = MockSupabase({"strategist_briefs": [{"headline": "x", ...}]})
        # later:
        assert sb._canned["_inserts"] == [("strategist_briefs", {...})]
    """

    def __init__(self, canned: dict | None = None):
        self._canned: dict = canned or {}

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._canned)


@pytest.fixture
def mock_supabase() -> MockSupabase:
    """A fresh MockSupabase with no canned data. Tests that need rows
    construct their own via `mock_supabase_factory({"table": [...]})`."""
    return MockSupabase()


@pytest.fixture
def mock_supabase_factory():
    """Factory fixture — tests call this to build a MockSupabase pre-loaded
    with canned rows.

        sb = mock_supabase_factory({"strategist_briefs": [{...}]})

    Exposed as a fixture (not an importable class) because pytest doesn't
    treat `tests/` as an importable package by default — fixtures are the
    canonical way to share helpers across test modules.
    """
    return MockSupabase


# ── Useful primitives ─────────────────────────────────────────────────────
@pytest.fixture
def real_uuid() -> str:
    """A fresh UUID string. Use anywhere we need a "real" org_id / thread_id
    that passes `_is_real_uuid()` — distinct from the dev fallback "dev"."""
    return str(uuid.uuid4())


@pytest.fixture
def langley_profile() -> OrgProfile:
    """The Langley Outdoors Academy fixture profile from config/orgs/. Used
    as the standard test tenant for template renders + profile-aware nodes."""
    return load_profile("langley-outdoors-academy")
