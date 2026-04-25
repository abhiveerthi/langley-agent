"""
Checkpointer lifecycle — `init_checkpointer` / `close_checkpointer` /
`get_checkpointer` and the AsyncPostgresSaver-vs-MemorySaver routing.

The lifespan-managed AsyncPostgresSaver path requires a live Postgres,
which we don't run in CI. Tests here verify:

  - The lazy `get_checkpointer()` fallback always returns a MemorySaver
    so test paths and ad-hoc scripts work without setup.
  - `init_checkpointer()` falls back to MemorySaver when DATABASE_URL is
    unset (dev), and propagates errors when ENVIRONMENT=production.
  - `close_checkpointer()` is a clean no-op for the MemorySaver path.
  - The AsyncPostgresSaver branch enters its async context and calls
    `setup()` exactly once (verified via mocks).
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import graph_orchestrator as orch
from langgraph.checkpoint.memory import MemorySaver


@pytest.fixture(autouse=True)
def _reset_orchestrator_state(monkeypatch):
    """Wipe the module-level checkpointer singleton before every test so
    init/close lifecycle assertions can't leak across tests."""
    orch._checkpointer = None
    orch._checkpointer_cm = None
    yield
    # Cleanup — don't leave a real connection open if a test escaped.
    orch._checkpointer = None
    orch._checkpointer_cm = None


# ── Lazy fallback (no init_checkpointer call) ─────────────────────────────
class TestLazyFallback:
    def test_get_checkpointer_returns_memorysaver_when_uninitialised(self):
        ckpt = orch.get_checkpointer()
        assert isinstance(ckpt, MemorySaver)

    def test_get_checkpointer_caches_the_singleton(self):
        first = orch.get_checkpointer()
        second = orch.get_checkpointer()
        assert first is second  # same instance — paused state survives across calls


# ── init_checkpointer routing ─────────────────────────────────────────────
class TestInitCheckpointer:
    @pytest.mark.asyncio
    async def test_dev_no_database_url_falls_back_to_memorysaver(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        await orch.init_checkpointer()
        assert isinstance(orch._checkpointer, MemorySaver)
        assert orch._checkpointer_cm is None

    @pytest.mark.asyncio
    async def test_dev_with_unreachable_postgres_falls_back(self, monkeypatch):
        """If DATABASE_URL points at a Postgres that's down, dev mode falls
        back to MemorySaver rather than refusing to start."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://nope:nope@127.0.0.1:1/x")
        monkeypatch.setenv("ENVIRONMENT", "development")

        # Patch the async context manager so __aenter__ raises.
        broken_cm = MagicMock()
        broken_cm.__aenter__ = AsyncMock(side_effect=ConnectionError("nope"))
        with patch(
            "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string",
            return_value=broken_cm,
        ):
            await orch.init_checkpointer()

        assert isinstance(orch._checkpointer, MemorySaver)
        assert orch._checkpointer_cm is None

    @pytest.mark.asyncio
    async def test_production_with_unreachable_postgres_raises(self, monkeypatch):
        """Production must fail loud — we don't want paused approvals
        silently dropping out of persistence in production."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://nope:nope@127.0.0.1:1/x")
        monkeypatch.setenv("ENVIRONMENT", "production")

        broken_cm = MagicMock()
        broken_cm.__aenter__ = AsyncMock(side_effect=ConnectionError("nope"))
        with patch(
            "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string",
            return_value=broken_cm,
        ):
            with pytest.raises(ConnectionError):
                await orch.init_checkpointer()

    @pytest.mark.asyncio
    async def test_postgres_path_enters_cm_and_calls_setup(self, monkeypatch):
        """Happy path — DATABASE_URL set, Postgres reachable. Verify the
        context manager is entered and setup() runs exactly once."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/x")
        monkeypatch.setenv("ENVIRONMENT", "development")

        fake_saver = MagicMock(name="AsyncPostgresSaver")
        fake_saver.setup = AsyncMock()
        fake_cm = MagicMock(name="cm")
        fake_cm.__aenter__ = AsyncMock(return_value=fake_saver)
        fake_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string",
            return_value=fake_cm,
        ):
            await orch.init_checkpointer()

        fake_cm.__aenter__.assert_awaited_once()
        fake_saver.setup.assert_awaited_once()
        assert orch._checkpointer is fake_saver
        assert orch._checkpointer_cm is fake_cm

    @pytest.mark.asyncio
    async def test_init_is_idempotent(self, monkeypatch):
        """Calling init twice doesn't re-enter the cm or re-run setup."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/x")

        fake_saver = MagicMock()
        fake_saver.setup = AsyncMock()
        fake_cm = MagicMock()
        fake_cm.__aenter__ = AsyncMock(return_value=fake_saver)
        fake_cm.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string",
            return_value=fake_cm,
        ):
            await orch.init_checkpointer()
            await orch.init_checkpointer()

        fake_cm.__aenter__.assert_awaited_once()  # NOT awaited twice
        fake_saver.setup.assert_awaited_once()


# ── close_checkpointer ────────────────────────────────────────────────────
class TestCloseCheckpointer:
    @pytest.mark.asyncio
    async def test_close_runs_aexit_on_postgres_path(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/x")
        fake_saver = MagicMock()
        fake_saver.setup = AsyncMock()
        fake_cm = MagicMock()
        fake_cm.__aenter__ = AsyncMock(return_value=fake_saver)
        fake_cm.__aexit__ = AsyncMock(return_value=None)
        with patch(
            "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string",
            return_value=fake_cm,
        ):
            await orch.init_checkpointer()
            await orch.close_checkpointer()
        fake_cm.__aexit__.assert_awaited_once()
        assert orch._checkpointer is None
        assert orch._checkpointer_cm is None

    @pytest.mark.asyncio
    async def test_close_is_noop_for_memorysaver(self, monkeypatch):
        """MemorySaver fallback has no context manager — close should not
        raise and should still null out the singleton."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        await orch.init_checkpointer()
        assert isinstance(orch._checkpointer, MemorySaver)
        await orch.close_checkpointer()
        assert orch._checkpointer is None

    @pytest.mark.asyncio
    async def test_close_swallows_aexit_errors(self, monkeypatch):
        """If __aexit__ raises (broken connection at shutdown time), close
        still completes — better than blocking app teardown."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/x")
        fake_saver = MagicMock()
        fake_saver.setup = AsyncMock()
        fake_cm = MagicMock()
        fake_cm.__aenter__ = AsyncMock(return_value=fake_saver)
        fake_cm.__aexit__ = AsyncMock(side_effect=RuntimeError("conn broken"))
        with patch(
            "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver.from_conn_string",
            return_value=fake_cm,
        ):
            await orch.init_checkpointer()
            # Should NOT raise.
            await orch.close_checkpointer()
        assert orch._checkpointer is None


# ── Integration with _compile_agent ───────────────────────────────────────
class TestCompileAgent:
    @pytest.mark.asyncio
    async def test_compile_uses_current_checkpointer(self):
        """_compile_agent should pass whatever get_checkpointer() returns
        to graph.compile — verifies the orchestrator's checkpointer wiring."""
        from packages.agents.registry import get_agent
        agent = get_agent("strategist")

        # Force a known MemorySaver into the singleton so we can assert
        # graph.compile receives it.
        sentinel = MemorySaver()
        orch._checkpointer = sentinel

        with patch.object(agent.graph, "compile") as mock_compile:
            mock_compile.return_value = MagicMock()
            await orch._compile_agent(agent)
        mock_compile.assert_called_once()
        kwargs = mock_compile.call_args.kwargs
        assert kwargs["checkpointer"] is sentinel
        assert kwargs["interrupt_before"] == agent.interrupt_before_nodes
