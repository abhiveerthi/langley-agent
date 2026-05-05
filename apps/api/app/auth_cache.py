"""
In-process auth cache: token → resolved user, with a short TTL.

Why this exists
---------------
`get_current_user` runs on every authenticated request and used to do
two roundtrips per call:

  1. `supabase.auth.get_user(token)` — Supabase Auth API, ~50–200ms
  2. `org_members` SELECT — Postgres, ~10–50ms

A single page load fires 3-5 API calls in parallel, each redoing both
of those for the same JWT. Caching the resolved `CurrentUser` (or
`AuthenticatedUser`) for a short window collapses that work into a
single roundtrip per token across the cluster of requests.

Design notes
------------
- **Bounded**: a soft cap of 10k entries with naive eviction of the
  oldest. Far more than any realistic active-token concurrency; bound
  exists so a forged-token DoS can't unbounded-grow the dict.
- **Per-process**: not Redis. Each API replica has its own cache. Cold
  hits on a freshly-spawned replica re-verify; a hot replica with a
  busy user keeps that user's token in cache. That's fine: this isn't
  a consistency-critical cache and the TTL is short.
- **Race-tolerant**: no locks. supabase-py is sync, so the GIL
  serializes dict ops; a race-on-fill at worst means two requests both
  verify a token and the second cache-write wins. Benign.
- **Errors NOT cached**: 401s and the 409 "you have a pending invite"
  path bypass the cache. The user could be retrying after fixing
  whatever was wrong; we don't want to make them wait out the TTL.
"""
from __future__ import annotations

import time
from typing import Generic, Optional, TypeVar

# 60s strikes the balance: long enough to dedup the bursts that come
# from a single page load (3-5 calls in 1-2s), short enough that a role
# change or invite acceptance propagates quickly without a manual flush.
DEFAULT_TTL_SECONDS = 60.0

# Soft cap. With 10k tokens cached at ~200 bytes each, the cache costs
# ~2MB — invisible. Beyond that the cluster is large enough that you'd
# move to Redis anyway.
DEFAULT_MAX_SIZE = 10_000


T = TypeVar("T")


class TtlCache(Generic[T]):
    """Tiny TTL cache. Generic so the same machinery backs both
    `CurrentUser` and `AuthenticatedUser` lookups without re-implementing
    the bookkeeping."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_size: int = DEFAULT_MAX_SIZE,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_size
        # Insert order is preserved (Python 3.7+), so the first key is
        # the oldest. Used by the simple FIFO eviction below.
        self._store: dict[str, tuple[T, float]] = {}

    def get(self, key: str) -> Optional[T]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() >= expires_at:
            # Lazy expiry — only evict on read. Fine: stale-but-unread
            # entries waste a few bytes for a short window, no harm.
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: T) -> None:
        # Drop any existing entry first so the new one lands at the end
        # of insertion order (resets its position in the FIFO eviction
        # queue — counts as "recent" again).
        self._store.pop(key, None)
        self._store[key] = (value, time.monotonic() + self._ttl)
        if len(self._store) > self._max:
            # Naive FIFO eviction. We don't need true LRU here — popping
            # the oldest insertion ages out tokens that haven't been
            # refreshed, which is what we want anyway.
            oldest = next(iter(self._store))
            self._store.pop(oldest, None)

    def invalidate(self, key: str) -> None:
        """Drop a specific entry. Useful for an explicit logout hook
        someday — not used by current code paths."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Wipe everything. Tests use this; no production caller."""
        self._store.clear()

    def size(self) -> int:
        """Visible-for-tests: how many entries are currently held."""
        return len(self._store)
