"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Hash, Loader2, Plus } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";
import { ChannelView } from "@/components/channels/ChannelView";
import { NewChannelModal } from "@/components/channels/NewChannelModal";
import { buildMentionableMaps } from "@/components/channels/utils";
import type {
  Channel,
  MentionableAgent,
  MentionableMaps,
  MentionableUser,
} from "@/components/channels/types";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type ChannelsState =
  | { state: "loading" }
  | { state: "ready"; items: Channel[] }
  | { state: "error"; message: string };

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

/**
 * The Channels page — Slack-style team chat where humans and agents are
 * first-class participants in the same channel. The left rail lists every
 * channel in the org; the center column hosts the selected channel.
 *
 * Page-level state covers:
 *   - The channel list (and the selected channel id).
 *   - The mentionable lookup maps used by both the composer's autocomplete
 *     and the realtime row resolver inside ChannelView. We refresh the
 *     maps when the channel switches because a different channel might
 *     surface members or agents we didn't have cached yet.
 *   - The "+ New channel" modal.
 *
 * Per-channel state (messages, scroll position, draft text) lives inside
 * ChannelView and is naturally reset across channel switches via the
 * `key={channel.id}` prop.
 */
export default function ChannelsPage() {
  const [channels, setChannels] = useState<ChannelsState>({ state: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mentionable, setMentionable] = useState<MentionableMaps | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const fetchChannels = useCallback(async (): Promise<Channel[] | null> => {
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setChannels({ state: "error", message: "Not signed in" });
        return null;
      }
      const res = await fetch(`${API}/api/channels`, { headers: auth });
      if (!res.ok) {
        setChannels({ state: "error", message: `HTTP ${res.status}` });
        return null;
      }
      const items = (await res.json()) as Channel[];
      setChannels({ state: "ready", items });
      return items;
    } catch (e) {
      setChannels({ state: "error", message: (e as Error).message });
      return null;
    }
  }, []);

  const fetchMentionable = useCallback(async (): Promise<void> => {
    try {
      const auth = await authHeader();
      if (!auth.Authorization) return;
      const res = await fetch(`${API}/api/channels/mentionable`, { headers: auth });
      if (!res.ok) return;
      const data = (await res.json()) as {
        agents: MentionableAgent[];
        users: MentionableUser[];
      };
      setMentionable(buildMentionableMaps(data.agents ?? [], data.users ?? []));
    } catch {
      // Mentionable being unavailable is non-fatal — the composer still
      // works without autocomplete and the message resolver falls back
      // to the API per-row.
    }
  }, []);

  // Initial load — defer state writes via queueMicrotask to satisfy the
  // React 19 `react-hooks/set-state-in-effect` lint, same convention used
  // on /app/tasks and /app/approvals.
  useEffect(() => {
    queueMicrotask(() => {
      void (async () => {
        const items = await fetchChannels();
        if (items && items.length > 0) {
          setSelectedId(items[0].id);
        }
        await fetchMentionable();
      })();
    });
  }, [fetchChannels, fetchMentionable]);

  // Refresh mentionable on channel switch so newly-added members/agents
  // surface in autocomplete + the realtime resolver without a full reload.
  useEffect(() => {
    if (!selectedId) return;
    queueMicrotask(() => {
      void fetchMentionable();
    });
  }, [selectedId, fetchMentionable]);

  // Mark the selected channel read locally — the server sync is fired by
  // ChannelView after it actually shows the user the messages. Locally
  // resetting the count keeps the sidebar honest the moment the user
  // clicks the channel rather than after the realtime "read" propagates.
  useEffect(() => {
    if (!selectedId) return;
    queueMicrotask(() => {
      setChannels((prev) =>
        prev.state === "ready"
          ? {
              state: "ready",
              items: prev.items.map((c) =>
                c.id === selectedId ? { ...c, unread_count: 0 } : c,
              ),
            }
          : prev,
      );
    });
  }, [selectedId]);

  // Org-wide subscription on `channel_messages` INSERTs — bumps the
  // sidebar badge for any channel that's not currently open. The
  // ChannelView component runs its own per-channel subscription on top
  // of this for the open channel; the two coexist fine.
  //
  // We only have an INSERT filter at the channel level; here we rely
  // on RLS to scope across the org. Noisy on huge orgs but bounded by
  // total messages-per-second across one workspace's channels — fine
  // for v1.
  useEffect(() => {
    const supabase = createClient();
    const ch = supabase
      .channel("channels-page-inbox")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "channel_messages" },
        (payload) => {
          const row = payload.new as {
            channel_id: string;
            sender_user_id: string | null;
          };
          // The currently-selected channel doesn't get a badge bump —
          // ChannelView is rendering it and will mark-read shortly.
          if (row.channel_id === selectedId) return;
          setChannels((prev) => {
            if (prev.state !== "ready") return prev;
            const idx = prev.items.findIndex((c) => c.id === row.channel_id);
            if (idx < 0) return prev;
            const next = [...prev.items];
            next[idx] = {
              ...next[idx],
              unread_count: next[idx].unread_count + 1,
            };
            return { state: "ready", items: next };
          });
        },
      )
      .subscribe();
    return () => {
      supabase.removeChannel(ch);
    };
  }, [selectedId]);

  // Stabilize the channel array reference so downstream useMemo deps don't
  // re-run on every render — without this the `[]` literal in the falsy
  // branch would be a fresh array each pass.
  const items = useMemo<Channel[]>(
    () => (channels.state === "ready" ? channels.items : []),
    [channels],
  );
  const selected = useMemo(
    () => items.find((c) => c.id === selectedId) ?? null,
    [items, selectedId],
  );

  async function handleCreate(input: { name: string; description: string | null }) {
    const auth = await authHeader();
    const res = await fetch(`${API}/api/channels`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...auth },
      body: JSON.stringify(input),
    });
    if (!res.ok) {
      // Throw so NewChannelModal can render the error inline. We surface
      // a slightly friendlier message for the most common backend reject
      // (uniqueness + regex validation).
      const text = await res.text().catch(() => "");
      throw new Error(text || `HTTP ${res.status}`);
    }
    const created = (await res.json()) as Channel;
    // Refetch to get the canonical list (with member_count etc) and
    // auto-select the new channel.
    const next = await fetchChannels();
    setSelectedId(created.id);
    if (!next?.some((c) => c.id === created.id)) {
      // Defensive — if for some reason the GET didn't include it yet,
      // splice it in so the UI doesn't lose the channel just made.
      setChannels((prev) =>
        prev.state === "ready"
          ? { state: "ready", items: [created, ...prev.items] }
          : prev,
      );
    }
    setModalOpen(false);
  }

  return (
    <div className="flex h-full min-h-0">
      {/* Left rail — channel list */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-card/40">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h1 className="text-sm font-semibold tracking-tight text-foreground">
            Channels
          </h1>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {channels.state === "loading" && (
            <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading…
            </div>
          )}
          {channels.state === "error" && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {channels.message}
            </div>
          )}
          {channels.state === "ready" && items.length === 0 && (
            <div className="px-3 py-2 text-xs text-muted-foreground">
              No channels yet.
            </div>
          )}
          {channels.state === "ready" &&
            items.map((c) => {
              const isSelected = c.id === selectedId;
              const hasUnread = !isSelected && c.unread_count > 0;
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setSelectedId(c.id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm transition-colors",
                    isSelected
                      ? "bg-primary/15 text-primary font-medium"
                      : hasUnread
                        ? "text-foreground hover:bg-accent"
                        : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  <Hash className="h-3.5 w-3.5 shrink-0" />
                  <span
                    className={cn("truncate", hasUnread && "font-semibold")}
                  >
                    {c.name}
                  </span>
                  {hasUnread ? (
                    <span className="ml-auto rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-bold leading-none text-primary-foreground">
                      {c.unread_count > 99 ? "99+" : c.unread_count}
                    </span>
                  ) : (
                    <span className="ml-auto text-[10px] text-muted-foreground/60">
                      {c.member_count}
                    </span>
                  )}
                </button>
              );
            })}
        </div>

        <div className="border-t border-border p-2">
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="flex w-full items-center gap-2 rounded-md border border-dashed border-border px-3 py-1.5 text-sm text-muted-foreground hover:border-primary/40 hover:bg-accent hover:text-foreground transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            New channel
          </button>
        </div>
      </aside>

      {/* Center column — selected channel view */}
      <div className="flex-1 min-w-0">
        {selected && mentionable ? (
          // key forces a fresh ChannelView mount per channel switch so all
          // per-channel state (messages, scroll, draft, realtime sub) is
          // torn down + rebuilt cleanly.
          <ChannelView
            key={selected.id}
            channel={selected}
            mentionable={mentionable}
          />
        ) : selected && !mentionable ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading channel…
            </div>
          </div>
        ) : channels.state === "ready" && items.length === 0 ? (
          <EmptyState onNewChannel={() => setModalOpen(true)} />
        ) : channels.state === "loading" ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading channels…
            </div>
          </div>
        ) : (
          <PickAChannel />
        )}
      </div>

      <NewChannelModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onCreate={handleCreate}
      />
    </div>
  );
}

function PickAChannel() {
  return (
    <div className="flex h-full items-center justify-center text-center">
      <div>
        <Hash className="mx-auto h-8 w-8 text-muted-foreground/40" />
        <p className="mt-2 text-sm font-medium text-foreground">Pick a channel</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Choose one from the left to start chatting.
        </p>
      </div>
    </div>
  );
}

function EmptyState({ onNewChannel }: { onNewChannel: () => void }) {
  return (
    <div className="flex h-full items-center justify-center text-center px-6">
      <div className="max-w-sm">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 border border-primary/20">
          <Hash className="h-6 w-6 text-primary" />
        </div>
        <h2 className="mt-3 text-base font-semibold text-foreground">
          No channels yet
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Channels are like Slack rooms — your team and your agents post in
          them together. Create one to get started.
        </p>
        <button
          onClick={onNewChannel}
          className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Create your first channel
        </button>
      </div>
    </div>
  );
}
