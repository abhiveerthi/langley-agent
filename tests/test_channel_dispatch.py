"""
Channel agent dispatch tests.

The dispatch helper runs an agent against a triggering message and posts
the agent's final response into the channel as a `sender_agent_id`
message. We mock `stream_new_run` and `_compile_agent` so no real LLMs
fire — what we care about here is the post-dispatch behavior:

  1. Happy path → final AIMessage posted as channel message
  2. Unknown / unregistered agent slug → fallback message
  3. Run paused at interrupt (approval gate) → fallback explaining it
  4. LLM raises → fallback "couldn't respond"
  5. State has no AIMessage content → fallback explaining it ran but
     didn't produce a response
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.services import channel_dispatch as cd


# ── Mock supabase that captures inserts ───────────────────────────────────
class _MockResult:
    def __init__(self, data):
        self.data = data


class _MockQuery:
    def __init__(self, table_name: str, store: dict):
        self._table = table_name
        self._store = store
        self._filters: dict = {}
        self._mode = "select"
        self._insert_payload: dict | None = None

    def select(self, *_a, **_k):
        self._mode = "select"
        return self
    def eq(self, k, v):
        self._filters[k] = v
        return self
    def limit(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def insert(self, payload: dict):
        self._mode = "insert"
        self._insert_payload = payload
        return self

    def execute(self):
        if self._mode == "insert" and self._insert_payload is not None:
            new_row = {"id": str(uuid.uuid4()), **self._insert_payload}
            self._store.setdefault(self._table, []).append(new_row)
            self._store.setdefault("_inserts", []).append((self._table, new_row))
            return _MockResult([new_row])
        rows = self._store.get(self._table, [])
        out = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
        return _MockResult(out)


class MockSupabase:
    def __init__(self, store=None):
        self._store = store if store is not None else {}
    def table(self, name):
        return _MockQuery(name, self._store)


# ── Fixtures ──────────────────────────────────────────────────────────────
@pytest.fixture
def real_uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def trigger_ctx(real_uuid: str):
    """Common kwargs every dispatch call needs."""
    return {
        "channel_id": str(uuid.uuid4()),
        "org_id": real_uuid,
        "user_id": str(uuid.uuid4()),
        "triggering_message_id": str(uuid.uuid4()),
        "triggering_message_body": "@strategist what should we make next?",
    }


def _agent_inserts(sb: MockSupabase) -> list[dict]:
    """Pull just the `channel_messages` inserts from the capture log."""
    return [
        row for table, row in sb._store.get("_inserts", [])
        if table == "channel_messages"
    ]


def _make_state(*, next_=(), messages=None) -> SimpleNamespace:
    """Build a fake LangGraph state snapshot."""
    return SimpleNamespace(
        next=next_,
        values={"messages": messages or []},
    )


async def _empty_stream(*_a, **_k):
    """Stand-in for `stream_new_run` that yields nothing — drains instantly."""
    if False:
        yield  # pragma: no cover


async def _failing_stream(*_a, **_k):
    """Stand-in for `stream_new_run` that raises mid-drain."""
    raise RuntimeError("LLM unavailable")
    yield  # pragma: no cover


# ── Dispatch happy path ───────────────────────────────────────────────────
@pytest.mark.asyncio
class TestDispatchHappyPath:
    async def test_posts_final_aimessage_as_channel_message(
        self, real_uuid, trigger_ctx,
    ):
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })

        final_state = _make_state(
            next_=(),  # empty → not paused
            messages=[
                HumanMessage(content="trigger"),
                AIMessage(content="here's what I'd make next: a hooks reel."),
            ],
        )

        fake_app = SimpleNamespace(aget_state=AsyncMock(return_value=final_state))

        with (
            patch.object(cd, "stream_new_run", _empty_stream),
            patch.object(cd, "_compile_agent", AsyncMock(return_value=fake_app)),
        ):
            await cd.dispatch_agent_to_channel(
                agent_slug="strategist", supabase=sb, **trigger_ctx,
            )

        inserts = _agent_inserts(sb)
        assert len(inserts) == 1
        msg = inserts[0]
        assert msg["sender_agent_id"] == agent_uuid
        assert "hooks reel" in msg["body"]
        assert msg["in_reply_to_message_id"] == trigger_ctx["triggering_message_id"]

    async def test_handles_content_block_list(self, real_uuid, trigger_ctx):
        """Anthropic returns content as a list of blocks; the helper must
        flatten the text blocks before posting."""
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })

        block_msg = AIMessage(content=[
            {"type": "text", "text": "first block"},
            {"type": "text", "text": " then second block"},
        ])
        final_state = _make_state(next_=(), messages=[block_msg])

        fake_app = SimpleNamespace(aget_state=AsyncMock(return_value=final_state))

        with (
            patch.object(cd, "stream_new_run", _empty_stream),
            patch.object(cd, "_compile_agent", AsyncMock(return_value=fake_app)),
        ):
            await cd.dispatch_agent_to_channel(
                agent_slug="strategist", supabase=sb, **trigger_ctx,
            )

        msg = _agent_inserts(sb)[0]
        assert msg["body"] == "first block then second block"


# ── Dispatch failure / fallback paths ─────────────────────────────────────
@pytest.mark.asyncio
class TestDispatchFallbacks:
    async def test_unregistered_agent_slug_posts_fallback(self, real_uuid, trigger_ctx):
        """Unknown slug — not even in AGENT_REGISTRY — gets a clear fallback."""
        sb = MockSupabase({"agents": []})

        await cd.dispatch_agent_to_channel(
            agent_slug="nonexistent-agent", supabase=sb, **trigger_ctx,
        )
        msgs = _agent_inserts(sb)
        assert len(msgs) == 1
        assert "isn't registered for this workspace" in msgs[0]["body"]
        # No agent id since the agent doesn't exist.
        assert msgs[0]["sender_agent_id"] is None

    async def test_missing_org_agent_row_posts_fallback(self, real_uuid, trigger_ctx):
        """Slug exists in code but no row in `agents` table for this org."""
        sb = MockSupabase({"agents": []})  # no agents row at all

        await cd.dispatch_agent_to_channel(
            agent_slug="strategist", supabase=sb, **trigger_ctx,
        )
        msgs = _agent_inserts(sb)
        assert len(msgs) == 1
        assert "isn't registered for this workspace" in msgs[0]["body"]

    async def test_paused_at_interrupt_posts_approval_card(self, real_uuid, trigger_ctx):
        """Happy path for the agent-paused branch: orchestrator wrote an
        approvals row with this thread_id, dispatch finds it, posts a
        channel message with metadata pointing at the approval id so the
        FE renders the inline approval card with Approve/Reject buttons."""
        agent_uuid = str(uuid.uuid4())
        approval_uuid = str(uuid.uuid4())
        # Approval row matches on (org_id, thread_id, status='pending').
        # We don't know the dispatch's generated thread_id ahead of time;
        # the lookup uses .eq("thread_id", ...) so we need our fixture to
        # match whatever thread_id the dispatch generated. Easiest: stub
        # the lookup function directly.
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })
        paused_state = _make_state(next_=("approval_gate",), messages=[])
        fake_app = SimpleNamespace(aget_state=AsyncMock(return_value=paused_state))

        with (
            patch.object(cd, "stream_new_run", _empty_stream),
            patch.object(cd, "_compile_agent", AsyncMock(return_value=fake_app)),
            patch.object(cd, "_resolve_pending_approval_id", return_value=approval_uuid),
        ):
            await cd.dispatch_agent_to_channel(
                agent_slug="strategist", supabase=sb, **trigger_ctx,
            )

        msgs = _agent_inserts(sb)
        assert len(msgs) == 1
        body = msgs[0]["body"]
        # Body is the search-friendly summary; the metadata is what the
        # FE branches on to actually render the card.
        assert "approval" in body.lower()
        assert msgs[0]["sender_agent_id"] == agent_uuid
        assert msgs[0]["metadata"] == {
            "kind": "approval",
            "approval_id": approval_uuid,
        }

    async def test_paused_at_interrupt_with_no_approval_row_falls_back(
        self, real_uuid, trigger_ctx,
    ):
        """Defensive fallback: dispatch detected a pause but couldn't
        locate the matching approvals row (race / DB hiccup). Channel
        message degrades to a text fallback pointing at /app/approvals
        rather than rendering a card with no actionable id."""
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })
        paused_state = _make_state(next_=("approval_gate",), messages=[])
        fake_app = SimpleNamespace(aget_state=AsyncMock(return_value=paused_state))

        with (
            patch.object(cd, "stream_new_run", _empty_stream),
            patch.object(cd, "_compile_agent", AsyncMock(return_value=fake_app)),
            patch.object(cd, "_resolve_pending_approval_id", return_value=None),
        ):
            await cd.dispatch_agent_to_channel(
                agent_slug="strategist", supabase=sb, **trigger_ctx,
            )

        msgs = _agent_inserts(sb)
        assert len(msgs) == 1
        body = msgs[0]["body"]
        assert "paused for your approval" in body
        assert "/app/approvals" in body
        # No metadata payload — FE renders the body as plain text.
        assert msgs[0].get("metadata") in (None, {})

    async def test_llm_failure_posts_fallback(self, real_uuid, trigger_ctx):
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })

        with patch.object(cd, "stream_new_run", _failing_stream):
            await cd.dispatch_agent_to_channel(
                agent_slug="strategist", supabase=sb, **trigger_ctx,
            )

        msgs = _agent_inserts(sb)
        assert len(msgs) == 1
        assert "couldn't respond" in msgs[0]["body"]
        assert msgs[0]["sender_agent_id"] == agent_uuid

    async def test_no_aimessage_in_state_posts_fallback(self, real_uuid, trigger_ctx):
        """Run completed but didn't emit any AIMessage with content — surface
        that to the channel rather than silently dropping it."""
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })
        # Only HumanMessages, no AIMessage with content.
        empty_state = _make_state(
            next_=(),
            messages=[HumanMessage(content="trigger")],
        )
        fake_app = SimpleNamespace(aget_state=AsyncMock(return_value=empty_state))

        with (
            patch.object(cd, "stream_new_run", _empty_stream),
            patch.object(cd, "_compile_agent", AsyncMock(return_value=fake_app)),
        ):
            await cd.dispatch_agent_to_channel(
                agent_slug="strategist", supabase=sb, **trigger_ctx,
            )

        msgs = _agent_inserts(sb)
        assert len(msgs) == 1
        assert "didn't produce a response" in msgs[0]["body"]


# ── Bypass-mention guarantee ──────────────────────────────────────────────
@pytest.mark.asyncio
class TestNoReDispatchLoop:
    async def test_agent_message_inserts_with_empty_mention_arrays(
        self, real_uuid, trigger_ctx,
    ):
        """Critical safety property — agent-authored messages must never
        carry parsed mention arrays. If they did, a `@publisher` quoted
        in the strategist's reply would re-trigger the publisher dispatch
        and so on, infinite loop."""
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })
        # Quote a fake mention in the response body — should still not
        # cause the inserted row to carry mentions.
        final_state = _make_state(
            next_=(),
            messages=[AIMessage(content="@publisher should ship this.")],
        )
        fake_app = SimpleNamespace(aget_state=AsyncMock(return_value=final_state))

        with (
            patch.object(cd, "stream_new_run", _empty_stream),
            patch.object(cd, "_compile_agent", AsyncMock(return_value=fake_app)),
        ):
            await cd.dispatch_agent_to_channel(
                agent_slug="strategist", supabase=sb, **trigger_ctx,
            )

        msg = _agent_inserts(sb)[0]
        assert msg["mentioned_user_ids"] == []
        assert msg["mentioned_agent_slugs"] == []


# ── Resume-from-channel path ──────────────────────────────────────────────
@pytest.mark.asyncio
class TestDispatchResumeToChannel:
    """Cover `dispatch_resume_to_channel` — the post-approve / post-reject
    path that drains the resume stream and posts the agent's continuation
    back into the channel.

    The orchestrator's resume helpers (`stream_resume_approved` /
    `stream_resume_rejected`) handle approval-row updates internally; we
    mock them out here to focus on what the dispatcher does AFTER the
    resume completes."""

    async def _make_approval(
        self, *, real_uuid: str, agent_slug: str = "strategist",
    ) -> tuple[str, str, dict]:
        """Build an approval row dict + the (approval_id, thread_id)
        tuple used to drive the resume call."""
        approval_id = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())
        return approval_id, thread_id, {
            "id": approval_id,
            "org_id": real_uuid,
            "thread_id": thread_id,
            "requested_by_agent": agent_slug,
            "status": "pending",
        }

    async def test_resume_approve_posts_agent_response(self, real_uuid, trigger_ctx):
        """Approve resumes, agent runs to completion, final AIMessage is
        posted to the channel as the continuation."""
        approval_id, thread_id, approval_row = await self._make_approval(real_uuid=real_uuid)
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })

        # Mock the approval store get to return the row by id.
        fake_store = SimpleNamespace(get=AsyncMock(return_value=approval_row))
        # Resume stream is drained; final state has a proper AIMessage.
        final_state = _make_state(
            next_=(), messages=[AIMessage(content="Email sent — Magpul received the pitch.")],
        )
        fake_app = SimpleNamespace(aget_state=AsyncMock(return_value=final_state))

        with (
            patch.object(cd, "get_approval_store", return_value=fake_store),
            patch.object(cd, "stream_resume_approved", _empty_stream),
            patch.object(cd, "_compile_agent", AsyncMock(return_value=fake_app)),
        ):
            await cd.dispatch_resume_to_channel(
                approval_id=approval_id,
                decision="approved",
                feedback=None,
                channel_id=trigger_ctx["channel_id"],
                org_id=real_uuid,
                user_id=trigger_ctx["user_id"],
                triggering_message_id=trigger_ctx["triggering_message_id"],
                supabase=sb,
            )

        msgs = _agent_inserts(sb)
        assert len(msgs) == 1
        assert "Email sent" in msgs[0]["body"]
        assert msgs[0]["sender_agent_id"] == agent_uuid

    async def test_resume_reject_routes_through_rejected_stream(
        self, real_uuid, trigger_ctx,
    ):
        """Reject hits stream_resume_rejected (not approved). The
        agent's revise branch runs and pauses again; we get a fresh
        approval card posted to the channel."""
        approval_id, thread_id, approval_row = await self._make_approval(real_uuid=real_uuid)
        new_approval_id = str(uuid.uuid4())
        agent_uuid = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"id": agent_uuid, "org_id": real_uuid, "slug": "strategist"}],
        })

        fake_store = SimpleNamespace(get=AsyncMock(return_value=approval_row))
        # After a rejection-driven revise, the graph pauses again at the
        # gate. The new pending approvals row would be a fresh id.
        paused_state = _make_state(next_=("approval_gate",), messages=[])
        fake_app = SimpleNamespace(aget_state=AsyncMock(return_value=paused_state))

        approved_called = AsyncMock()
        rejected_called = _empty_stream

        with (
            patch.object(cd, "get_approval_store", return_value=fake_store),
            patch.object(cd, "stream_resume_approved", approved_called),
            patch.object(cd, "stream_resume_rejected", rejected_called),
            patch.object(cd, "_compile_agent", AsyncMock(return_value=fake_app)),
            patch.object(cd, "_resolve_pending_approval_id", return_value=new_approval_id),
        ):
            await cd.dispatch_resume_to_channel(
                approval_id=approval_id,
                decision="rejected",
                feedback="too long",
                channel_id=trigger_ctx["channel_id"],
                org_id=real_uuid,
                user_id=trigger_ctx["user_id"],
                triggering_message_id=trigger_ctx["triggering_message_id"],
                supabase=sb,
            )

        # Approve stream MUST NOT have fired.
        approved_called.assert_not_called()
        # New approval card was posted referencing the new id.
        msgs = _agent_inserts(sb)
        assert len(msgs) == 1
        assert msgs[0]["metadata"] == {"kind": "approval", "approval_id": new_approval_id}

    async def test_resume_with_missing_approval_row_logs_and_returns(
        self, real_uuid, trigger_ctx,
    ):
        """Resume called with an approval_id that no longer exists in
        the store. Don't crash; don't post anything — the channel-side
        UPDATE already marked the card resolved synchronously."""
        sb = MockSupabase()
        fake_store = SimpleNamespace(get=AsyncMock(return_value=None))

        with patch.object(cd, "get_approval_store", return_value=fake_store):
            await cd.dispatch_resume_to_channel(
                approval_id=str(uuid.uuid4()),
                decision="approved",
                feedback=None,
                channel_id=trigger_ctx["channel_id"],
                org_id=real_uuid,
                user_id=trigger_ctx["user_id"],
                triggering_message_id=trigger_ctx["triggering_message_id"],
                supabase=sb,
            )

        # Nothing inserted.
        assert _agent_inserts(sb) == []
