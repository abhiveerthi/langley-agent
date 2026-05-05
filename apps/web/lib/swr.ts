"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Tiny stale-while-revalidate hook backed by localStorage.
 *
 * Why we have our own (instead of pulling in `swr` or `react-query`):
 *   - We use it in two narrow places (slow-changing org config + integration
 *     status pills), not as the app's general data layer.
 *   - Adds zero deps and ~70 lines that are easy to reason about.
 *   - Bundle stays smaller than pulling in a 7KB+ lib for two callsites.
 *
 * Behaviour:
 *   - First mount with no cache: `isLoading=true`, fetch fires, results cached.
 *   - Mount with a cache hit: `isLoading=false` and `data` is the cached value
 *     IMMEDIATELY (no flash of empty state); a background revalidate fires.
 *     If the revalidate succeeds, `data` is replaced with the fresh value.
 *     If it fails, the cached value stays — best-effort, never worse than
 *     before.
 *   - The cache survives reloads and tabs (it's localStorage). Different
 *     users on the same browser will share a cache; we don't currently
 *     support that scenario in v1 (single-user-per-browser-profile is the
 *     assumed model).
 *
 * Not handled (intentionally):
 *   - Cross-tab synchronisation (no `storage` event listener — caller's
 *     callsite usually mounts once per page).
 *   - TTL-based eviction. Cached entries never expire on their own; the
 *     revalidate-on-mount handles freshness. Add a TTL guard if a callsite
 *     ever wants harder freshness guarantees.
 */

interface SwrResult<T> {
  data: T | undefined;
  error: Error | null;
  /** True only on first ever fetch (no cached value to show). */
  isLoading: boolean;
  /** Manually re-run the fetcher (e.g. user clicks "Retry"). */
  refresh: () => Promise<void>;
}

const CACHE_PREFIX = "marcus.swr.v1:";

function readCache<T>(key: string): T | undefined {
  if (typeof window === "undefined") return undefined; // SSR guard
  try {
    const raw = window.localStorage.getItem(CACHE_PREFIX + key);
    if (!raw) return undefined;
    return JSON.parse(raw) as T;
  } catch {
    return undefined;
  }
}

function writeCache<T>(key: string, value: T): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(value));
  } catch {
    // QuotaExceeded etc — non-fatal; the next mount just won't have a cache hit.
  }
}

/** Clear a specific cache key. Useful when an action invalidates the cached value. */
export function invalidateSwrCache(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(CACHE_PREFIX + key);
  } catch {
    /* no-op */
  }
}

export function useStaleWhileRevalidate<T>(
  key: string,
  fetcher: () => Promise<T>,
): SwrResult<T> {
  // Hold the fetcher in a ref so a non-memoized one (caller passes an
  // inline arrow per render) doesn't loop the revalidate effect.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const fresh = await fetcherRef.current();
      setData(fresh);
      setError(null);
      writeCache(key, fresh);
    } catch (e) {
      setError(e as Error);
    } finally {
      setIsLoading(false);
    }
  }, [key]);

  useEffect(() => {
    // Defer to a microtask so the sync render finishes before we
    // setState — clears the React 19 set-state-in-effect lint and
    // keeps the first paint cheap.
    queueMicrotask(() => {
      const cached = readCache<T>(key);
      if (cached !== undefined) {
        setData(cached);
        setIsLoading(false); // we have something to show; revalidate runs below
      }
      void refresh();
    });
  }, [key, refresh]);

  return { data, error, isLoading, refresh };
}
