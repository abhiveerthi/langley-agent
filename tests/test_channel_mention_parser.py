"""
Unit tests for the @-mention parser used by `POST /channels/{id}/messages`.

The parser is the load-bearing security boundary — what it reports as
mentioned drives both DB denormalization and agent dispatch. Tests cover
the regex extraction (token-level dedup, punctuation tolerance, no
matches inside email addresses) and the resolution layer (agent slugs vs
user names/emails, org-scoped lookup, multi-mention dedup).

The DB lookups go through MockSupabase — no real Postgres / Supabase.
"""
from __future__ import annotations

import uuid

import pytest

from app.routers.channels import _extract_mention_tokens, parse_mentions


@pytest.fixture
def real_uuid() -> str:
    return str(uuid.uuid4())


# ── Mock supabase shaped for `parse_mentions` ─────────────────────────────
class _MockResult:
    def __init__(self, data):
        self.data = data


class _MockQuery:
    """Captures filters for select(); no-op for the rest."""
    def __init__(self, table_name: str, store: dict):
        self._table = table_name
        self._store = store
        self._filters: dict = {}

    def select(self, *_a, **_k): return self
    def eq(self, k, v):
        self._filters[k] = v
        return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def is_(self, *_a, **_k): return self
    def lt(self, *_a, **_k): return self
    def in_(self, *_a, **_k): return self

    def execute(self):
        rows = self._store.get(self._table, [])
        # Apply equality filters; org_id is the only one we use for the parser.
        out = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
        return _MockResult(out)


class MockSupabase:
    def __init__(self, store=None):
        self._store = store or {}
    def table(self, name):
        return _MockQuery(name, self._store)


# ── Token extraction (pure) ───────────────────────────────────────────────
class TestExtractMentionTokens:
    def test_returns_empty_for_no_mentions(self):
        assert _extract_mention_tokens("just a regular message") == []

    def test_finds_single_mention(self):
        assert _extract_mention_tokens("hey @strategist what next?") == ["strategist"]

    def test_finds_multiple_mentions(self):
        tokens = _extract_mention_tokens("@strategist @publisher please coordinate")
        assert tokens == ["strategist", "publisher"]

    def test_lowercases_tokens(self):
        assert _extract_mention_tokens("@Strategist @PUBLISHER") == ["strategist", "publisher"]

    def test_dedups_repeated_mentions(self):
        tokens = _extract_mention_tokens("@strategist hey @strategist did you see @strategist")
        assert tokens == ["strategist"]

    def test_punctuation_after_mention_does_not_break(self):
        assert _extract_mention_tokens("@strategist, what's up? cc @publisher.") == [
            "strategist",
            "publisher",
        ]

    def test_does_not_match_inside_email(self):
        """`user@example.com` must not produce a `@example` mention."""
        assert _extract_mention_tokens("send to abhi@example.com please") == []

    def test_supports_hyphen_and_underscore_in_handle(self):
        assert _extract_mention_tokens("@brand-manager and @some_user") == [
            "brand-manager",
            "some_user",
        ]

    def test_ignores_lone_at_sign(self):
        assert _extract_mention_tokens("price is @ a discount") == []


# ── Resolution layer (agent vs user lookup) ───────────────────────────────
class TestParseMentions:
    def test_no_mentions_returns_empty(self, real_uuid):
        sb = MockSupabase()
        users, agents = parse_mentions("hello team", org_id=real_uuid, supabase=sb)
        assert users == []
        assert agents == []

    def test_single_agent_mention(self, real_uuid):
        sb = MockSupabase({
            "agents": [{"org_id": real_uuid, "slug": "strategist"}],
            "org_members": [],
        })
        users, agents = parse_mentions(
            "@strategist what should we make?",
            org_id=real_uuid,
            supabase=sb,
        )
        assert agents == ["strategist"]
        assert users == []

    def test_multi_agent_mention(self, real_uuid):
        sb = MockSupabase({
            "agents": [
                {"org_id": real_uuid, "slug": "strategist"},
                {"org_id": real_uuid, "slug": "publisher"},
            ],
            "org_members": [],
        })
        users, agents = parse_mentions(
            "@strategist @publisher coordinate please",
            org_id=real_uuid,
            supabase=sb,
        )
        assert agents == ["strategist", "publisher"]

    def test_unknown_slug_silently_dropped(self, real_uuid):
        """Mentioning an agent that isn't installed is a no-op rather than
        an error — the FE can't reliably distinguish typos from new agents."""
        sb = MockSupabase({
            "agents": [{"org_id": real_uuid, "slug": "strategist"}],
            "org_members": [],
        })
        users, agents = parse_mentions(
            "@unknown-slug should be skipped",
            org_id=real_uuid,
            supabase=sb,
        )
        assert agents == []
        assert users == []

    def test_user_mention_by_full_name(self, real_uuid):
        user_id = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [],
            "org_members": [
                {
                    "org_id": real_uuid,
                    "user_id": user_id,
                    "users": {
                        "id": user_id,
                        "full_name": "Abhi Veerthineni",
                        "email": "abhi@example.com",
                    },
                },
            ],
        })
        users, agents = parse_mentions(
            "hey @abhiveerthineni did you see this",
            org_id=real_uuid,
            supabase=sb,
        )
        assert users == [user_id]
        assert agents == []

    def test_user_mention_by_email_prefix(self, real_uuid):
        user_id = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [],
            "org_members": [
                {
                    "org_id": real_uuid,
                    "user_id": user_id,
                    "users": {
                        "id": user_id,
                        "full_name": "Abhi Veerthineni",
                        "email": "abhi@example.com",
                    },
                },
            ],
        })
        users, agents = parse_mentions(
            "@abhi please review",
            org_id=real_uuid,
            supabase=sb,
        )
        assert users == [user_id]

    def test_mixed_agent_and_user_mention(self, real_uuid):
        user_id = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"org_id": real_uuid, "slug": "strategist"}],
            "org_members": [
                {
                    "org_id": real_uuid,
                    "user_id": user_id,
                    "users": {
                        "id": user_id,
                        "full_name": "Abhi Veerthineni",
                        "email": "abhi@example.com",
                    },
                },
            ],
        })
        users, agents = parse_mentions(
            "@strategist + @abhi together",
            org_id=real_uuid,
            supabase=sb,
        )
        assert agents == ["strategist"]
        assert users == [user_id]

    def test_repeated_mentions_deduped(self, real_uuid):
        user_id = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [{"org_id": real_uuid, "slug": "strategist"}],
            "org_members": [
                {
                    "org_id": real_uuid,
                    "user_id": user_id,
                    "users": {
                        "id": user_id,
                        "full_name": "Abhi V",
                        "email": "abhi@example.com",
                    },
                },
            ],
        })
        users, agents = parse_mentions(
            "@strategist @strategist @abhi @abhi @abhi",
            org_id=real_uuid,
            supabase=sb,
        )
        assert agents == ["strategist"]
        assert users == [user_id]

    def test_punctuation_around_mention_resolves(self, real_uuid):
        sb = MockSupabase({
            "agents": [{"org_id": real_uuid, "slug": "strategist"}],
            "org_members": [],
        })
        users, agents = parse_mentions(
            "ping @strategist, please reply!",
            org_id=real_uuid,
            supabase=sb,
        )
        assert agents == ["strategist"]

    def test_no_match_inside_email_address(self, real_uuid):
        """A literal email in the body must not produce a mention even
        if the email's prefix happens to collide with an agent slug."""
        sb = MockSupabase({
            "agents": [{"org_id": real_uuid, "slug": "publisher"}],
            "org_members": [],
        })
        users, agents = parse_mentions(
            "forward to publisher@example.com",
            org_id=real_uuid,
            supabase=sb,
        )
        assert agents == []
        assert users == []

    def test_only_org_scoped_agents_resolve(self, real_uuid):
        """Agents in a different org must not resolve even if they share a slug."""
        other_org = str(uuid.uuid4())
        sb = MockSupabase({
            # Same slug 'strategist' but different org_id.
            "agents": [{"org_id": other_org, "slug": "strategist"}],
            "org_members": [],
        })
        users, agents = parse_mentions(
            "@strategist hello",
            org_id=real_uuid,
            supabase=sb,
        )
        assert agents == []

    def test_only_org_scoped_users_resolve(self, real_uuid):
        """Users not in the caller's org must not be mentioned."""
        other_org = str(uuid.uuid4())
        other_user_id = str(uuid.uuid4())
        sb = MockSupabase({
            "agents": [],
            "org_members": [
                {
                    "org_id": other_org,
                    "user_id": other_user_id,
                    "users": {
                        "id": other_user_id,
                        "full_name": "Outsider User",
                        "email": "outsider@example.com",
                    },
                },
            ],
        })
        users, agents = parse_mentions(
            "@outsider should not match",
            org_id=real_uuid,
            supabase=sb,
        )
        assert users == []
