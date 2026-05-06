"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Check, Loader2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Notification = {
  id: string;
  type: string;
  title: string;
  body: string | null;
  action_url: string | null;
  read: boolean;
  metadata: Record<string, unknown> | null;
  created_at: string;
};

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const m = diff / 60_000;
  if (m < 1) return "just now";
  if (m < 60) return `${Math.floor(m)}m`;
  const h = m / 60;
  if (h < 24) return `${Math.floor(h)}h`;
  const d = h / 24;
  if (d < 7) return `${Math.floor(d)}d`;
  return new Date(iso).toLocaleDateString();
}

/**
 * Notifications bell — top-right of the TopBar. Shows the unread-count
 * badge inline; clicking opens a dropdown with the most recent 10
 * notifications. Each entry deep-links via `action_url` (today only
 * `channel_mention` rows populate this — `/app/channels?channel=<id>`).
 *
 * v1 scope:
 *   - GET /api/notifications on mount + on dropdown open + every 60s
 *   - PATCH /api/notifications/{id}/read on item click
 *   - PATCH /api/notifications/read-all from the header button
 *   - No realtime subscription on the `notifications` table — adding
 *     it is one Supabase publication line + a `.on('postgres_changes')`
 *     hook for a future PR. The 60s poll is fine until we have
 *     evidence users want sub-minute latency.
 */
export function NotificationsBell() {
  const [items, setItems] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const auth = await authHeader();
      if (!auth.Authorization) return;
      const res = await fetch(`${API}/api/notifications`, { headers: auth });
      if (!res.ok) return;
      const rows = (await res.json()) as Notification[];
      setItems(rows);
    } catch {
      // Network errors here are non-fatal — we'll retry on the next
      // poll / focus / dropdown open.
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load + 60s poll + refetch on tab focus.
  useEffect(() => {
    queueMicrotask(() => {
      void fetchItems();
    });
    const int = setInterval(fetchItems, 60_000);
    function onFocus() {
      void fetchItems();
    }
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(int);
      window.removeEventListener("focus", onFocus);
    };
  }, [fetchItems]);

  // Refetch when the user opens the dropdown — fresher data with no
  // racing on the poll interval.
  useEffect(() => {
    if (open) {
      queueMicrotask(() => {
        void fetchItems();
      });
    }
  }, [open, fetchItems]);

  // Outside-click closes the dropdown.
  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const unreadCount = items.filter((n) => !n.read).length;

  async function markOneRead(n: Notification) {
    if (n.read) return;
    // Optimistic — flip to read in local state. Failure is logged; the
    // next fetch re-syncs.
    setItems((prev) =>
      prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)),
    );
    try {
      const auth = await authHeader();
      await fetch(`${API}/api/notifications/${n.id}/read`, {
        method: "PATCH",
        headers: auth,
      });
    } catch {
      // ignore
    }
  }

  async function markAllRead() {
    if (markingAll) return;
    setMarkingAll(true);
    setItems((prev) => prev.map((x) => ({ ...x, read: true })));
    try {
      const auth = await authHeader();
      await fetch(`${API}/api/notifications/read-all`, {
        method: "PATCH",
        headers: auth,
      });
    } catch {
      // ignore
    } finally {
      setMarkingAll(false);
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Notifications${unreadCount ? ` (${unreadCount} unread)` : ""}`}
        className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span className="absolute right-0.5 top-0.5 flex min-w-[16px] items-center justify-center rounded-full bg-primary px-1 py-px text-[9px] font-bold leading-none text-primary-foreground">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-40 mt-2 w-80 overflow-hidden rounded-lg border border-border bg-card shadow-xl">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Notifications
            </span>
            <button
              type="button"
              onClick={() => void markAllRead()}
              disabled={unreadCount === 0 || markingAll}
              className="inline-flex items-center gap-1 rounded text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40"
            >
              {markingAll ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Check className="h-3 w-3" />
              )}
              Mark all read
            </button>
          </div>

          <div className="max-h-96 overflow-y-auto">
            {loading && items.length === 0 && (
              <div className="flex items-center justify-center px-3 py-6 text-xs text-muted-foreground">
                <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                Loading…
              </div>
            )}
            {!loading && items.length === 0 && (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                You&apos;re all caught up.
              </div>
            )}
            {items.slice(0, 10).map((n) => (
              <NotificationItem
                key={n.id}
                notification={n}
                onClick={() => void markOneRead(n)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function NotificationItem({
  notification: n,
  onClick,
}: {
  notification: Notification;
  onClick: () => void;
}) {
  const inner = (
    <div
      className={cn(
        "flex flex-col gap-0.5 px-3 py-2.5 hover:bg-accent transition-colors border-b border-border/50 last:border-b-0",
        !n.read && "bg-primary/5",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-foreground">{n.title}</span>
        <span className="shrink-0 text-[10px] text-muted-foreground/70">
          {relativeTime(n.created_at)}
        </span>
      </div>
      {n.body && (
        <span className="line-clamp-2 text-xs text-muted-foreground">
          {n.body}
        </span>
      )}
    </div>
  );
  // Internal action_url → next/link (instant client nav). External /
  // missing → render as a button so the click handler still fires.
  if (n.action_url && n.action_url.startsWith("/")) {
    return (
      <Link href={n.action_url} onClick={onClick}>
        {inner}
      </Link>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className="block w-full text-left"
    >
      {inner}
    </button>
  );
}
