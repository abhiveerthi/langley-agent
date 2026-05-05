"""
`get_supabase` returns a process-wide cached Client per (url, key).

Repeatedly calling it with the same Settings should return the SAME
Client instance (no rebuild). Different Settings → different Client.

Why we care: constructing a Client builds GoTrueClient + PostgrestClient
+ RealtimeClient + StorageClient under the hood, each with httpx Clients.
Doing that on every request was meaningful per-call CPU + GC pressure
for no value (the configuration is fixed for the process lifetime).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import Settings
from app.dependencies import _supabase_clients, get_supabase


@pytest.fixture(autouse=True)
def _clear_singleton_cache():
    """Each test starts with an empty cache so we can assert on first-
    call construction behaviour deterministically."""
    _supabase_clients.clear()
    yield
    _supabase_clients.clear()


def _settings(url: str = "https://abc.supabase.co", key: str = "service-key") -> Settings:
    """Build a Settings instance with just the supabase fields populated.
    Other fields fall back to whatever Settings.model_construct chooses."""
    return Settings.model_construct(supabase_url=url, supabase_service_key=key)


class TestGetSupabaseSingleton:
    def test_returns_same_instance_for_same_settings(self):
        with patch("app.dependencies.create_client") as mock_create:
            sentinel = object()
            mock_create.return_value = sentinel

            settings = _settings()
            first = get_supabase(settings)
            second = get_supabase(settings)
            third = get_supabase(settings)

            assert first is sentinel
            assert second is sentinel
            assert third is sentinel
            # Only constructed once.
            assert mock_create.call_count == 1
            mock_create.assert_called_with("https://abc.supabase.co", "service-key")

    def test_different_settings_get_different_clients(self):
        """Defensive — if we ever route different cohorts to different
        Supabase projects, the cache must not return one cohort's client
        to another."""
        with patch("app.dependencies.create_client") as mock_create:
            client_a = object()
            client_b = object()
            mock_create.side_effect = [client_a, client_b]

            a = get_supabase(_settings("https://a.supabase.co", "key-a"))
            b = get_supabase(_settings("https://b.supabase.co", "key-b"))

            assert a is client_a
            assert b is client_b
            assert mock_create.call_count == 2

    def test_same_url_different_key_treated_as_distinct(self):
        """Anon vs service role would have the same url but different
        keys — they MUST not share a cached client (different permission
        scopes)."""
        with patch("app.dependencies.create_client") as mock_create:
            mock_create.side_effect = [object(), object()]
            url = "https://x.supabase.co"
            anon = get_supabase(_settings(url, "anon-key"))
            service = get_supabase(_settings(url, "service-key"))

            assert anon is not service
            assert mock_create.call_count == 2

    def test_clear_cache_forces_reconstruction(self):
        """Tests / a hot-reload path that clears the cache must produce
        a fresh client on the next call."""
        with patch("app.dependencies.create_client") as mock_create:
            mock_create.side_effect = [object(), object()]

            first = get_supabase(_settings())
            _supabase_clients.clear()
            second = get_supabase(_settings())

            assert first is not second
            assert mock_create.call_count == 2
