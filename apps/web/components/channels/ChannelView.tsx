"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AlertCircle, Hash, Loader2, Users } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { MessageRow } from "./MessageRow";
import { MessageComposer } from "./MessageComposer";
import type {
  Channel,
  ChannelMessage,
  MentionableMaps,
} from "./types";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ChannelViewProps {
  channel: Channel;
  mentionable: MentionableMaps;
}

type LoadState =
  | { state: "loading" }
  | { state: "ready" }
  | { state: "error"; message: string };

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

/**
 * The center column of the Channels page — header, scroll-back message
 * list, composer. Owns:
 *
 *   - The per-channel message cache. We refetch on channel switch (the
 *     parent re-renders us via `key={channel.id}`, so all per-channel
 *     state is naturally torn down).
 *   - The Supabase realtime subscription. One subscription per render of
 *     this component instance; the `key=channel.id` upstream guarantees
 *     mount/unmount rather than re-keying so we never end up subscribed
 *     to two channels at once.
 *   - Auto-scroll behavior: stick to the bottom only if the user was
 *     already at the bottom when a new message arrives. This keeps reading
 *     scrollback uninterrupted while still feeling live.
 */
export function ChannelView({ channel, mentionable }: ChannelViewProps) {
  const [messages, setMessages] = useState<ChannelMessage[]>([]);
  const [load, setLoad] = useState<LoadState>({ state: "loading" });

  // Track whether the user is "pinned" to the bottom. A small slack of 64px
  // tolerates wobble (font metrics, keyboard popping) without false negatives.
  const scrollerRef = useRef<HTMLDivElement>(null);
  const wasAtBottomRef = useRef(true);

  // Fetch the most-recent page of messages.
  const fetchMessages = useCallback(async () => {
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setLoad({ state: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(
        `${API}/api/channels/${channel.id}/messages?limit=50`,
        { headers: auth },
      );
      if (!res.ok) {
        setLoad({ state: "error", message: `HTTP ${res.status}` });
        return;
      }
      // API returns newest-first; we render oldest-at-top for chat order.
      const rows = (await res.json()) as ChannelMessage[];
      setMessages([...rows].reverse());
      setLoad({ state: "ready" });
    } catch (e) {
      setLoad({ state: "error", message: (e as Error).message });
    }
  }, [channel.id]);

  // Initial load. We use queueMicrotask to defer the state writes outside
  // useEffect's synchronous body — same pattern as /app/tasks. This satisfies
  // React 19's `react-hooks/set-state-in-effect` lint.
  useEffect(() => {
    queueMicrotask(() => {
      void fetchMessages();
    });
  }, [fetchMessages]);

  /**
   * One-shot resolver for a realtime row whose `sender_*_id` doesn't
   * resolve through the local mentionable maps (e.g. a brand-new agent
   * was added mid-session). We pull that single message back from the
   * API, which returns the joined sender info, and append it. This is a
   * graceful corner case — most messages resolve inline.
   */
  const refetchOne = useCallback(
    async (messageId: string) => {
      try {
        const auth = await authHeader();
        const res = await fetch(
          `${API}/api/channels/${channel.id}/messages?limit=1`,
          { headers: auth },
        );
        if (!res.ok) return;
        const rows = (await res.json()) as ChannelMessage[];
        const found = rows.find((m) => m.id === messageId);
        if (!found) return;
        setMessages((prev) =>
          prev.some((m) => m.id === found.id) ? prev : [...prev, found],
        );
      } catch {
        // Swallow — the realtime row is already lost; refreshing is the
        // user's escape hatch. We don't want to surface a banner for every
        // unresolved sender.
      }
    },
    [channel.id],
  );

  // Realtime subscription. The dependency array is intentionally short:
  // we resubscribe only when the channel changes. The mentionable maps
  // are read out of state at event time (closure capture is fine because
  // they only change between channel switches in practice — and even
  // when they refresh mid-session the stale closure still holds correct
  // FK ids; the worst case is one missed icon and a refetch fallback).
  useEffect(() => {
    const supabase = createClient();
    const ch = supabase
      .channel(`channel:${channel.id}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "channel_messages",
          filter: `channel_id=eq.${channel.id}`,
        },
        (payload) => {
          const row = payload.new as Partial<ChannelMessage> & {
            id: string;
            channel_id: string;
            org_id: string;
            sender_user_id: string | null;
            sender_agent_id: string | null;
            body: string;
            mentioned_user_ids: string[];
            mentioned_agent_slugs: string[];
            agent_run_id: string | null;
            in_reply_to_message_id: string | null;
            created_at: string;
            edited_at: string | null;
          };

          // Resolve the sender locally from the mentionable maps. Both
          // user-id and agent-id lookups are O(1) — the `/mentionable`
          // payload includes the agents-table id explicitly so realtime
          // INSERTs (which only carry FK ids) never need a refetch in the
          // common case.
          let sender_user: ChannelMessage["sender_user"] = null;
          let sender_agent: ChannelMessage["sender_agent"] = null;
          if (row.sender_user_id) {
            const u = mentionable.usersById[row.sender_user_id];
            if (u) sender_user = { id: u.id, full_name: u.full_name, email: u.email };
          }
          if (row.sender_agent_id) {
            const a = mentionable.agentsById[row.sender_agent_id];
            if (a) sender_agent = { id: a.id, slug: a.slug, name: a.name, icon: a.icon };
          }

          if (!sender_user && !sender_agent) {
            // Sender added to the org / agents list mid-session — fall
            // through to a one-shot refetch which returns the joined sender.
            void refetchOne(row.id);
            return;
          }

          const message: ChannelMessage = {
            id: row.id,
            channel_id: row.channel_id,
            org_id: row.org_id,
            sender_user_id: row.sender_user_id,
            sender_agent_id: row.sender_agent_id,
            sender_user,
            sender_agent,
            body: row.body,
            mentioned_user_ids: row.mentioned_user_ids ?? [],
            mentioned_agent_slugs: row.mentioned_agent_slugs ?? [],
            agent_run_id: row.agent_run_id,
            in_reply_to_message_id: row.in_reply_to_message_id,
            created_at: row.created_at,
            edited_at: row.edited_at,
          };

          setMessages((prev) => {
            // Dedupe — optimistic insert may have placed this id already,
            // and we'll trust the realtime row as canonical.
            if (prev.some((m) => m.id === message.id)) {
              return prev.map((m) => (m.id === message.id ? message : m));
            }
            return [...prev, message];
          });
        },
      )
      .subscribe();

    return () => {
      supabase.removeChannel(ch);
    };
  }, [channel.id, mentionable, refetchOne]);

  // Track scroll position so we know whether to auto-scroll on new arrivals.
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const handler = () => {
      const distanceFromBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight;
      wasAtBottomRef.current = distanceFromBottom < 64;
    };
    el.addEventListener("scroll", handler, { passive: true });
    return () => el.removeEventListener("scroll", handler);
  }, []);

  // Auto-scroll on new message IF user was already pinned to the bottom.
  // A separate effect rather than inside the realtime callback so we can
  // also stick after the initial fetch finishes painting.
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    if (wasAtBottomRef.current) {
      // RAF so layout has settled with the new row.
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
    }
  }, [messages]);

  /**
   * POST a new message. Optimistically insert a synthetic row so the UI
   * snaps; the realtime echo will dedupe by id when it arrives. On failure
   * we drop the synthetic row and rethrow so the composer can keep the draft.
   */
  const onSend = useCallback(
    async (body: string): Promise<string | null> => {
      const auth = await authHeader();
      const tempId = `temp-${crypto.randomUUID()}`;

      // Best-effort optimistic sender — uses whichever org user we can
      // identify from the auth session. We don't have that user's display
      // name in the mentionable list (it's "you"), so we fall back to a
      // placeholder; the realtime dedupe replaces it with the canonical row.
      const optimistic: ChannelMessage = {
        id: tempId,
        channel_id: channel.id,
        org_id: "",
        sender_user_id: null,
        sender_agent_id: null,
        sender_user: { id: "me", full_name: "You", email: "you" },
        sender_agent: null,
        body,
        mentioned_user_ids: [],
        mentioned_agent_slugs: [],
        agent_run_id: null,
        in_reply_to_message_id: null,
        created_at: new Date().toISOString(),
        edited_at: null,
      };
      setMessages((prev) => [...prev, optimistic]);
      // Force-pin to the bottom on send, even if the user had scrolled up —
      // sending is an explicit "I want to see what I just wrote" gesture.
      wasAtBottomRef.current = true;

      try {
        const res = await fetch(
          `${API}/api/channels/${channel.id}/messages`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", ...auth },
            body: JSON.stringify({ body }),
          },
        );
        if (!res.ok) {
          // Roll back the optimistic row.
          setMessages((prev) => prev.filter((m) => m.id !== tempId));
          throw new Error(`HTTP ${res.status}`);
        }
        const real = (await res.json()) as ChannelMessage;
        // Replace temp row with canonical one (realtime will then no-op).
        setMessages((prev) =>
          prev.map((m) => (m.id === tempId ? real : m)),
        );
        return real.id;
      } catch (e) {
        setMessages((prev) => prev.filter((m) => m.id !== tempId));
        throw e;
      }
    },
    [channel.id],
  );

  // Build a quick lookup so MessageRow can resolve `in_reply_to_message_id`
  // to a parent message we already have rendered without each row scanning
  // the array on its own.
  const messageById = useMemo(() => {
    const m: Record<string, ChannelMessage> = {};
    for (const msg of messages) m[msg.id] = msg;
    return m;
  }, [messages]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="border-b border-border px-6 py-3">
        <div className="flex items-center gap-2">
          <Hash className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-base font-semibold text-foreground">
            {channel.name}
          </h2>
          <div className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
            <Users className="h-3 w-3" />
            {channel.member_count} {channel.member_count === 1 ? "member" : "members"}
          </div>
        </div>
        {channel.description && (
          <p className="mt-0.5 text-xs text-muted-foreground line-clamp-1">
            {channel.description}
          </p>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollerRef} className="flex-1 overflow-y-auto min-h-0">
        {load.state === "loading" && (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading messages…
            </div>
          </div>
        )}
        {load.state === "error" && (
          <div className="m-6 rounded-md border border-destructive/40 bg-destructive/10 p-4">
            <div className="flex items-center gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4" />
              Couldn&apos;t load messages: {load.message}
            </div>
            <button
              onClick={fetchMessages}
              className="mt-2 rounded-md border border-border px-3 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              Retry
            </button>
          </div>
        )}
        {load.state === "ready" && messages.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <Hash className="h-8 w-8 text-muted-foreground/40 mx-auto mb-2" />
              <p className="text-sm font-medium text-foreground">
                No messages yet in #{channel.name}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Say hi — or @mention an agent to kick things off.
              </p>
            </div>
          </div>
        )}
        {load.state === "ready" && messages.length > 0 && (
          <div className="py-2">
            {messages.map((m) => (
              <MessageRow
                key={m.id}
                message={m}
                mentionable={mentionable}
                replyTo={
                  m.in_reply_to_message_id
                    ? (messageById[m.in_reply_to_message_id] ?? null)
                    : null
                }
              />
            ))}
          </div>
        )}
      </div>

      {/* Composer */}
      <MessageComposer
        channelName={channel.name}
        mentionable={mentionable}
        onSend={onSend}
        disabled={load.state !== "ready"}
      />
    </div>
  );
}
