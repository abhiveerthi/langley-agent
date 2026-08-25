"""
Live delegation — the DM front door actually running the specialist.

No live Slack, no LLM, no Supabase. Covers:
  - the collector contract (arm / queue / cap / truncate / disarm)
  - ContextVar propagation into asyncio tasks (the mechanism the whole
    design rests on — LangGraph spawns internal tasks during a run)
  - delegate_task tool: live-dispatch branch vs file-a-board-task branch
  - spawn_delegated_run wiring: thread resolution keyed by the DELEGATED
    agent's slug, provenance on the persisted user turn, and the
    failure-note guarantee ("handed to broll" is never followed by silence)
"""
from __future__ import annotations

import asyncio

import pytest

from packages.agents.core import delegation


# ── Collector contract ─────────────────────────────────────────────────────
class TestCollector:
    def test_inactive_by_default(self):
        assert delegation.collector_active() is False
        assert delegation.queue_delegation("broll", "draft clips") is False

    def test_arm_queue_disarm(self):
        queue, token = delegation.activate_collector()
        try:
            assert delegation.collector_active() is True
            assert delegation.queue_delegation("broll", "draft 10 clips") is True
            assert queue == [{"agent_slug": "broll", "instruction": "draft 10 clips"}]
        finally:
            delegation.deactivate_collector(token)
        assert delegation.collector_active() is False

    def test_cap_enforced(self):
        queue, token = delegation.activate_collector()
        try:
            for i in range(delegation.MAX_DELEGATIONS_PER_RUN):
                assert delegation.queue_delegation("broll", f"job {i}") is True
            # An injected "delegate 50 tasks" must not fan out unbounded.
            assert delegation.queue_delegation("broll", "one too many") is False
            assert len(queue) == delegation.MAX_DELEGATIONS_PER_RUN
        finally:
            delegation.deactivate_collector(token)

    def test_instruction_truncated(self):
        queue, token = delegation.activate_collector()
        try:
            delegation.queue_delegation("broll", "x" * 100_000)
            assert len(queue[0]["instruction"]) == delegation.MAX_INSTRUCTION_CHARS
        finally:
            delegation.deactivate_collector(token)

    async def test_visible_inside_spawned_task(self):
        """LangGraph runs nodes in internally-spawned asyncio tasks, which
        snapshot the ambient context at creation — a queue armed before the
        run must be appendable from inside one."""
        queue, token = delegation.activate_collector()
        try:
            async def tool_call_deep_in_graph():
                return delegation.queue_delegation("strategist", "from a task")

            assert await asyncio.create_task(tool_call_deep_in_graph()) is True
            assert queue == [
                {"agent_slug": "strategist", "instruction": "from a task"}
            ]
        finally:
            delegation.deactivate_collector(token)


# ── delegate_task tool branches ────────────────────────────────────────────
class TestDelegateTaskDispatch:
    async def test_live_branch_queues_and_files_no_task(self, monkeypatch):
        from packages.agents.core import tasks as tasks_mod
        from packages.agents.image_reader.tools import delegate_task

        filed = []

        async def fake_create(**kwargs):
            filed.append(kwargs)
            return "task-1"

        monkeypatch.setattr(tasks_mod, "create_task_from_agent", fake_create)
        queue, token = delegation.activate_collector()
        try:
            reply = await delegate_task.ainvoke(
                {"agent_slug": "broll", "instruction": "Draft 10 clips on the debate"}
            )
        finally:
            delegation.deactivate_collector(token)
        assert queue == [
            {"agent_slug": "broll", "instruction": "Draft 10 clips on the debate"}
        ]
        assert filed == []  # live dispatch replaces the board task
        assert "reply in this thread" in reply

    async def test_live_branch_cap_message(self):
        from packages.agents.image_reader.tools import delegate_task

        queue, token = delegation.activate_collector()
        try:
            for i in range(delegation.MAX_DELEGATIONS_PER_RUN):
                delegation.queue_delegation("broll", f"job {i}")
            reply = await delegate_task.ainvoke(
                {"agent_slug": "broll", "instruction": "one more"}
            )
        finally:
            delegation.deactivate_collector(token)
        assert "limit" in reply.lower()
        assert len(queue) == delegation.MAX_DELEGATIONS_PER_RUN

    async def test_roster_gate_still_first(self):
        from packages.agents.image_reader.tools import delegate_task

        queue, token = delegation.activate_collector()
        try:
            reply = await delegate_task.ainvoke(
                {"agent_slug": "image-reader", "instruction": "recurse"}
            )
        finally:
            delegation.deactivate_collector(token)
        assert "isn't a delegatable agent" in reply
        assert queue == []


# ── spawn_delegated_run / _run_delegated_agent wiring ──────────────────────
def _canned_channel_rows():
    # _resolve_marcus_thread select returns [] → insert path runs and the
    # mapping row lands in MockSupabase._inserts.
    return {"slack_channels": []}


class TestDelegatedRun:
    async def test_runs_target_agent_on_its_own_thread(
        self, mock_supabase_factory, monkeypatch, real_uuid
    ):
        from app.services import slack_delegation as sd

        sb = mock_supabase_factory(_canned_channel_rows())
        ran = {}

        def fake_stream(**kwargs):
            # Record at CALL time — an async generator body wouldn't run
            # until iterated, and the patched _run_and_post never iterates.
            ran["stream_kwargs"] = kwargs

            async def _gen():
                yield "data: {}\n\n"

            return _gen()

        async def fake_run_and_post(**kwargs):
            ran["post_kwargs"] = kwargs

        monkeypatch.setattr(sd, "stream_new_run", fake_stream)
        monkeypatch.setattr(sd, "_run_and_post", fake_run_and_post)

        await sd._run_delegated_agent(
            supabase=sb,
            org_id=real_uuid,
            user_id="u1",
            bot_token="xoxb-1",
            scopes=[],
            slack_team_id="T1",
            slack_channel_id="D1",
            root_ts="111.222",
            agent_slug="broll",
            instruction="Draft 10 clips",
        )

        # The delegated agent got its OWN Marcus thread, keyed by ITS slug
        # on the same Slack thread (thread_id == checkpointer key).
        mapping_inserts = [
            p for (t, p) in sb._canned.get("_inserts", []) if t == "slack_channels"
        ]
        assert mapping_inserts and mapping_inserts[0]["agent_slug"] == "broll"
        assert mapping_inserts[0]["slack_thread_root_ts"] == "111.222"
        assert ran["stream_kwargs"]["agent_slug"] == "broll"
        assert "Draft 10 clips" in ran["stream_kwargs"]["message"]
        # The persisted user turn carries delegation provenance.
        msg_inserts = [
            p for (t, p) in sb._canned.get("_inserts", []) if t == "messages"
        ]
        assert msg_inserts and msg_inserts[0]["metadata"]["delegated_by"] == "image-reader"
        # Reply posts to the same Slack thread under the broll persona.
        assert ran["post_kwargs"]["root_ts"] == "111.222"
        assert ran["post_kwargs"]["slack_channel_id"] == "D1"

    async def test_failure_posts_note_not_silence(
        self, mock_supabase_factory, monkeypatch, real_uuid
    ):
        from app.services import slack_delegation as sd

        sb = mock_supabase_factory(_canned_channel_rows())
        posted = []

        async def boom(**kwargs):
            raise RuntimeError("orchestrator down")

        async def fake_post(token, channel, text, **kwargs):
            posted.append(text)
            return {"ts": "1"}

        monkeypatch.setattr(sd, "_run_and_post", boom)
        monkeypatch.setattr(
            sd.slack_client, "post_message_in_thread", fake_post
        )

        await sd._run_delegated_agent(
            supabase=sb,
            org_id=real_uuid,
            user_id="u1",
            bot_token="xoxb-1",
            scopes=[],
            slack_team_id="T1",
            slack_channel_id="D1",
            root_ts="111.222",
            agent_slug="broll",
            instruction="Draft 10 clips",
        )
        # _run_and_post only raises from its tail Slack posts — the work
        # ran, so the note must warn against blind re-runs (double spend).
        assert posted and "couldn't deliver" in posted[0]
        assert "repeat completed work" in posted[0]

    async def test_pre_run_failure_note_says_couldnt_start(
        self, mock_supabase_factory, monkeypatch, real_uuid
    ):
        from app.services import slack_delegation as sd

        posted = []

        def resolve_boom(*_a, **_k):
            raise RuntimeError("db down")

        async def fake_post(token, channel, text, **kwargs):
            posted.append(text)
            return {"ts": "1"}

        monkeypatch.setattr(sd, "_resolve_marcus_thread", resolve_boom)
        monkeypatch.setattr(
            sd.slack_client, "post_message_in_thread", fake_post
        )

        await sd._run_delegated_agent(
            supabase=mock_supabase_factory(_canned_channel_rows()),
            org_id=real_uuid,
            user_id="u1",
            bot_token="xoxb-1",
            scopes=[],
            slack_team_id="T1",
            slack_channel_id="D1",
            root_ts="111.222",
            agent_slug="broll",
            instruction="Draft 10 clips",
        )
        # Nothing ran — safe (and correct) to invite a retry.
        assert posted and "couldn't start" in posted[0]

    async def test_spawn_creates_tracked_task(self, monkeypatch, real_uuid):
        from app.services import slack_delegation as sd

        done = asyncio.Event()

        async def fake_run(**kwargs):
            done.set()

        monkeypatch.setattr(sd, "_run_delegated_agent", fake_run)
        sd.spawn_delegated_run(
            supabase=None,
            org_id=real_uuid,
            user_id="u1",
            bot_token="xoxb-1",
            scopes=[],
            slack_team_id="T1",
            slack_channel_id="D1",
            root_ts="1.2",
            agent_slug="broll",
            instruction="x",
        )
        await asyncio.wait_for(done.wait(), timeout=2)
        # Strong ref released once the task completes.
        await asyncio.sleep(0)
        assert not sd._delegated_tasks


# ── Event dedup + per-slug coalescing + spend cap ──────────────────────────
class TestEventDedup:
    def test_duplicate_event_id_suppressed(self):
        from app.routers import slack_events as se

        se._seen_events.clear()
        assert se._already_seen("Ev123") is False   # first delivery
        assert se._already_seen("Ev123") is True    # Slack retry → suppressed
        assert se._already_seen("Ev456") is False

    def test_missing_event_id_never_suppressed(self):
        from app.routers import slack_events as se

        # No id → can't dedupe; dropping would lose real messages.
        assert se._already_seen(None) is False
        assert se._already_seen(None) is False


class TestDispatchCoalescing:
    def test_same_slug_coalesced_into_one_run(self, monkeypatch):
        from app.services import slack_runner as sr
        from app.services import slack_delegation as sd

        spawned = []
        monkeypatch.setattr(
            sd, "spawn_delegated_run", lambda **kw: spawned.append(kw)
        )
        sr._dispatch_delegations(
            [
                {"agent_slug": "broll", "instruction": "clips on the debate"},
                {"agent_slug": "broll", "instruction": "clips on the fishing trip"},
                {"agent_slug": "strategist", "instruction": "weekly angle"},
            ],
            supabase=None, org_id="o", user_id="u", bot_token="t",
            scopes=[], slack_team_id="T1", slack_channel_id="D1", root_ts="1.2",
        )
        # Two broll asks → ONE run (two concurrent runs would race one
        # checkpointer thread); strategist untouched.
        assert len(spawned) == 2
        broll = next(s for s in spawned if s["agent_slug"] == "broll")
        assert "1. clips on the debate" in broll["instruction"]
        assert "2. clips on the fishing trip" in broll["instruction"]

    def test_empty_queue_spawns_nothing(self, monkeypatch):
        from app.services import slack_runner as sr
        from app.services import slack_delegation as sd

        monkeypatch.setattr(
            sd, "spawn_delegated_run",
            lambda **kw: (_ for _ in ()).throw(AssertionError("spawned")),
        )
        sr._dispatch_delegations(
            [], supabase=None, org_id="o", user_id="u", bot_token="t",
            scopes=[], slack_team_id="T", slack_channel_id="D", root_ts="1",
        )


class TestBrollChatSpendCap:
    async def test_generate_capped_and_concurrent(self, monkeypatch):
        import packages.agents.broll.agent as broll_mod
        from packages.agents.broll.agent import BRollAgent, MAX_CLIPS_PER_CHAT_RUN
        from packages.integrations import higgsfield

        calls = []

        async def fake_generate(prompt, **kwargs):
            calls.append(prompt)

            class Clip:
                aspect_ratio = kwargs.get("aspect_ratio", "16:9")
                duration_seconds = 6
                url = "https://x/clip.mp4"
                bytes_ = b"vid"

            return Clip()

        monkeypatch.setattr(higgsfield, "is_configured", lambda: True)
        monkeypatch.setattr(higgsfield, "generate_clip", fake_generate)

        agent = BRollAgent()
        plan = {"clips": [{"prompt": f"p{i}", "topic": "T"} for i in range(60)]}
        out = await agent._generate_clips_node(
            {"messages": [], "org_id": "dev", "metadata": {}, "plan": plan}
        )
        # An injected "generate 60 clips" renders at most the cap, and the
        # truncation is reported rather than silent.
        assert len(calls) == MAX_CLIPS_PER_CHAT_RUN
        assert len(out["metadata"]["clips"]) == MAX_CLIPS_PER_CHAT_RUN
        assert any("cap" in e for e in out["metadata"]["clip_errors"])

    def test_draft_and_generate_routes_to_draft_lane(self):
        from packages.agents.broll.agent import BRollAgent

        agent = BRollAgent()
        assert agent._route_by_intent({"intent": "draft_and_generate"}) == "draft_and_generate"
        # Unknown intents still collapse to general.
        assert agent._route_by_intent({"intent": "nonsense"}) == "general"
