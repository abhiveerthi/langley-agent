"""
Profile loader — UUID/DB path, YAML/slug path, dev fallback, failure modes.

Note: this branch ships the `tests/` directory ahead of the eval-harness PR
(which adds the top-level pyproject.toml + conftest.py). Until that lands,
this file defines its own minimal MockSupabase locally; once eval-harness
merges, the autouse `_reset_contextvars` fixture and `MockSupabase` from
conftest.py become available and we'll port this to use them.
"""
from __future__ import annotations

import uuid

import pytest

from packages.agents.core.profile import (
    Brand,
    Niche,
    OrgProfile,
    ProfileNotFound,
    YoutubeChannel,
    _generic_niche,
    _is_uuid,
    load_profile,
)
from packages.integrations.context import current_supabase


# ── Local mock Supabase (will be replaced by conftest fixture later) ─────
class _MockResult:
    def __init__(self, data: list[dict]):
        self.data = data


class _MockQuery:
    def __init__(self, table_name: str, canned: dict):
        self._table = table_name
        self._canned = canned

    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self

    def execute(self):
        return _MockResult(self._canned.get(self._table, []))


class MockSupabase:
    def __init__(self, canned: dict | None = None):
        self._canned = canned or {}

    def table(self, name: str) -> _MockQuery:
        return _MockQuery(name, self._canned)


@pytest.fixture(autouse=True)
def _reset_supabase_contextvar():
    """Wipe the supabase ContextVar before/after each test so DB-vs-YAML
    routing decisions can't leak across tests."""
    current_supabase.set(None)
    yield
    current_supabase.set(None)


@pytest.fixture
def real_uuid() -> str:
    return str(uuid.uuid4())


# ── Identifier classification ────────────────────────────────────────────
class TestIsUuid:
    @pytest.mark.parametrize("value, expected", [
        ("dev", False),
        ("", False),
        ("langley-outdoors-academy", False),
        ("123e4567-e89b-12d3-a456-426614174000", True),
    ])
    def test_classification(self, value, expected):
        assert _is_uuid(value) is expected


# ── Demo / dev fallback ───────────────────────────────────────────────────
class TestDemoFallback:
    @pytest.mark.parametrize("input_value", [None, "", "dev", "DEV", " dev "])
    def test_dev_inputs_return_demo_profile(self, input_value):
        p = load_profile(input_value)
        assert p.is_fixture is True
        assert p.brand.name == "Demo Channel"
        assert p.niche.slug == "demo"


# ── YAML path (slug-based) ────────────────────────────────────────────────
class TestYamlLoader:
    def test_langley_loads_with_real_niche(self):
        p = load_profile("langley-outdoors-academy")
        assert p.brand.name == "Langley Outdoors Academy"
        assert p.niche.slug == "conservative-firearms"
        assert "Tactical Gear" in p.niche.lead_categories
        assert p.youtube.channel_id == "UCGkAebzIWfSm7upwZ1UIsAg"
        assert p.is_fixture is False

    def test_missing_slug_raises(self):
        with pytest.raises(ProfileNotFound, match="No config/orgs/"):
            load_profile("nonexistent-slug")


# ── DB path (UUID-based) ──────────────────────────────────────────────────
class TestDbLoader:
    def test_uuid_with_no_db_row_returns_blank_profile(self, real_uuid):
        # current_supabase is None per autouse fixture, so the DB lookup
        # returns nothing. Loader returns a blank-but-real profile so agents
        # can still run for orgs that haven't filled in brand settings yet.
        p = load_profile(real_uuid)
        assert p.org_id == real_uuid
        assert p.is_fixture is False
        assert p.brand.name is None
        assert p.niche.slug == "generic"
        assert p.youtube.channel_id is None

    def test_uuid_with_db_row_loads(self, real_uuid):
        sb = MockSupabase({
            "org_profiles": [{
                "org_id": real_uuid,
                "brand_name": "Real Tenant Co",
                "brand_voice": "casual, witty",
                "brand_primary_email": "list@realtenant.co",
                "niche_slug": "gaming",
                "youtube_channel_id": "UCabcdef",
                "owners": ["owner@realtenant.co"],
                "is_fixture": False,
            }],
        })
        current_supabase.set(sb)
        p = load_profile(real_uuid)
        assert p.org_id == real_uuid
        assert p.brand.name == "Real Tenant Co"
        assert p.niche.slug == "gaming"  # resolved against config/niches/gaming.yaml
        assert p.niche.display_name == "Gaming / Esports"
        assert p.is_fixture is False

    def test_uuid_with_partial_db_row_falls_back_to_generic_niche(self, real_uuid):
        """Freshly-signed-up org has only the OAuth-known bits — no niche
        chosen yet. Loader fills generic niche so templates render."""
        sb = MockSupabase({
            "org_profiles": [{
                "org_id": real_uuid,
                "brand_name": "Mid-Onboarding Channel",
                "brand_voice": None,
                "niche_slug": None,
                "youtube_channel_id": "UCxyz",
                "owners": [],
                "is_fixture": False,
            }],
        })
        current_supabase.set(sb)
        p = load_profile(real_uuid)
        assert p.niche.slug == "generic"
        assert p.niche.display_name == "General creator content"

    def test_uuid_with_unknown_niche_slug_falls_back_to_generic(self, real_uuid):
        sb = MockSupabase({
            "org_profiles": [{
                "org_id": real_uuid,
                "brand_name": "X",
                "niche_slug": "totally-made-up-niche",
                "owners": [],
            }],
        })
        current_supabase.set(sb)
        p = load_profile(real_uuid)
        assert p.niche.slug == "generic"

    def test_uuid_with_db_error_returns_blank_profile(self, real_uuid):
        """If the DB query throws, treat it as a miss and return the blank
        profile rather than letting the underlying exception bubble — agent
        code should always see a usable profile or our blank fallback."""
        class _FaultyDB(MockSupabase):
            def table(self, name):
                raise Exception("network blip")

        current_supabase.set(_FaultyDB())
        p = load_profile(real_uuid)
        assert p.org_id == real_uuid
        assert p.is_fixture is False
        assert p.brand.name is None


# ── Niche resolution ──────────────────────────────────────────────────────
class TestNicheResolution:
    def test_default_factory_provides_generic_niche(self):
        """OrgProfile constructed without a niche kwarg defaults to generic
        so templates rendering `niche.display_name` don't crash."""
        p = OrgProfile(org_id="x")
        assert p.niche.slug == "generic"

    def test_generic_niche_renders_in_templates(self):
        """End-to-end: a profile with the generic niche fallback should
        render every agent's primary template without raising."""
        from packages.agents.core.templates import render

        bare_profile = OrgProfile(org_id="bare", is_fixture=True)
        for slug, template in [
            ("strategist", "system.j2"),
            ("brand_manager", "system.j2"),
            ("publisher", "system.j2"),
            ("community_manager", "triage.j2"),
        ]:
            extra = {"intent": "research"} if slug == "strategist" else {}
            out = render(slug, template, profile=bare_profile, **extra)
            assert "General creator content" in out, \
                f"{slug}/{template} didn't render generic niche display_name"


# ── OrgProfile shape ──────────────────────────────────────────────────────
class TestOrgProfileSchema:
    def test_minimal_construction(self):
        """All fields except org_id should have sensible defaults."""
        p = OrgProfile(org_id="x")
        assert isinstance(p.brand, Brand)
        assert isinstance(p.niche, Niche)
        assert isinstance(p.youtube, YoutubeChannel)
        assert p.owners == []
        assert p.is_fixture is False

    def test_brand_fields_optional(self):
        """Partial signup — brand name not yet set — should be valid."""
        b = Brand()
        assert b.name is None and b.voice is None and b.primary_email is None
