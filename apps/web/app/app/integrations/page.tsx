"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, CheckCircle, Loader2, Plus, RefreshCw } from "lucide-react";
import { integrations } from "@/lib/mock-data";
import { cn } from "@/lib/utils";
import { createClient } from "@/lib/supabase/client";

const categories = ["All", "Storage", "Communication", "Production", "Platform", "Finance", "Productivity"];

const iconColors: Record<string, string> = {
  dropbox: "bg-blue-500/20 text-blue-400",
  drive: "bg-emerald-500/20 text-emerald-400",
  gmail: "bg-red-500/20 text-red-400",
  youtube: "bg-red-600/20 text-red-500",
  notion: "bg-zinc-500/20 text-zinc-300",
  slack: "bg-violet-500/20 text-violet-400",
  frameio: "bg-blue-600/20 text-blue-300",
  stripe: "bg-indigo-500/20 text-indigo-400",
};

const iconInitials: Record<string, string> = {
  dropbox: "Db",
  drive: "GD",
  gmail: "Gm",
  youtube: "YT",
  notion: "No",
  slack: "Sl",
  frameio: "Fr",
  stripe: "St",
};

const categoryColors: Record<string, string> = {
  Storage: "bg-blue-500/15 text-blue-400",
  Communication: "bg-violet-500/15 text-violet-400",
  Production: "bg-pink-500/15 text-pink-400",
  Platform: "bg-red-500/15 text-red-400",
  Finance: "bg-emerald-500/15 text-emerald-400",
  Productivity: "bg-amber-500/15 text-amber-400",
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type YouTubeState =
  | { state: "loading" }
  | { state: "disconnected" }
  | {
      state: "connected";
      channel: { channel_title?: string; thumbnail?: string; subscriber_count?: number };
      scopes: string[];
      synced_at: string | null;
    }
  | { state: "error"; message: string };

export default function IntegrationsPage() {
  const [activeCategory, setActiveCategory] = useState("All");
  const [requestText, setRequestText] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [youtube, setYoutube] = useState<YouTubeState>({ state: "loading" });
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const router = useRouter();
  const searchParams = useSearchParams();

  const fetchYouTube = useCallback(async () => {
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) {
        setYoutube({ state: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/integrations/youtube/status`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) {
        setYoutube({ state: "error", message: `HTTP ${res.status}` });
        return;
      }
      const data = await res.json();
      if (!data.connected) {
        setYoutube({ state: "disconnected" });
        return;
      }
      setYoutube({
        state: "connected",
        channel: data.channel || {},
        scopes: data.scopes || [],
        synced_at: data.token_expires_at,
      });
    } catch (e) {
      setYoutube({ state: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    fetchYouTube();
  }, [fetchYouTube]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2200);
    return () => clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    const yt = searchParams.get("youtube");
    if (!yt) return;
    if (yt === "connected") setToast("YouTube connected");
    else if (yt === "error") {
      const reason = searchParams.get("reason") || "unknown";
      setToast(`YouTube connect failed: ${reason.slice(0, 80)}`);
    }
    const url = new URL(window.location.href);
    url.searchParams.delete("youtube");
    url.searchParams.delete("reason");
    router.replace(url.pathname + (url.search ? url.search : ""));
  }, [searchParams, router]);

  async function connectYouTube() {
    setBusy(true);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) {
        setToast("Sign in first");
        return;
      }
      const res = await fetch(`${API}/api/integrations/youtube/auth-url`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) {
        setToast(`Failed to start connect (HTTP ${res.status})`);
        return;
      }
      const { auth_url } = await res.json();
      window.location.href = auth_url;
    } finally {
      setBusy(false);
    }
  }

  async function disconnectYouTube() {
    setBusy(true);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const res = await fetch(`${API}/api/integrations/youtube`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (res.ok) {
        setToast("YouTube disconnected");
        setYoutube({ state: "disconnected" });
      } else {
        setToast(`Failed to disconnect (HTTP ${res.status})`);
      }
    } finally {
      setBusy(false);
    }
  }

  const filtered =
    activeCategory === "All"
      ? integrations
      : integrations.filter((i) => i.category === activeCategory);

  const connectedCount =
    (youtube.state === "connected" ? 1 : 0) +
    filtered.filter((i) => i.id !== "youtube" && i.connected).length;

  function handleRequest() {
    if (requestText.trim()) {
      setSubmitted(true);
      setTimeout(() => {
        setSubmitted(false);
        setRequestText("");
      }, 2000);
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Integrations</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect your tools to supercharge your workflow
        </p>
      </div>

      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2 text-sm">
          <div className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-foreground font-medium">{connectedCount} connected</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <div className="h-2 w-2 rounded-full bg-muted-foreground/40" />
          <span className="text-muted-foreground">{integrations.length - connectedCount} available</span>
        </div>
      </div>

      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={cn(
              "shrink-0 rounded-full px-4 py-1.5 text-xs font-medium transition-colors",
              activeCategory === cat
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:border-border/80 hover:text-foreground"
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((integration) => {
          if (integration.id === "youtube") {
            return (
              <YouTubeCard
                key={integration.id}
                state={youtube}
                busy={busy}
                onConnect={connectYouTube}
                onDisconnect={disconnectYouTube}
                onRefresh={fetchYouTube}
              />
            );
          }
          return (
            <div
              key={integration.id}
              className={cn(
                "rounded-lg border bg-card p-5 transition-colors",
                integration.connected ? "border-border" : "border-border hover:border-border/80"
              )}
            >
              <div className="mb-4 flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className={cn(
                      "flex h-10 w-10 items-center justify-center rounded-lg text-sm font-bold",
                      iconColors[integration.icon] ?? "bg-muted text-muted-foreground"
                    )}
                  >
                    {iconInitials[integration.icon] ?? integration.name[0]}
                  </div>
                  <div>
                    <p className="font-medium text-foreground">{integration.name}</p>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-xs font-medium",
                        categoryColors[integration.category] ?? "bg-muted text-muted-foreground"
                      )}
                    >
                      {integration.category}
                    </span>
                  </div>
                </div>
                {integration.connected && (
                  <div className="flex items-center gap-1 text-xs text-emerald-400">
                    <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    Live
                  </div>
                )}
              </div>

              <p className="mb-4 text-sm text-muted-foreground">{integration.description}</p>

              {integration.connected ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <CheckCircle className="h-3.5 w-3.5 text-emerald-400" />
                    <span>Connected &middot; Synced {integration.lastSync}</span>
                  </div>
                  <div className="flex gap-2">
                    <button className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-border py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
                      <RefreshCw className="h-3 w-3" />
                      Sync Now
                    </button>
                    <button className="flex-1 rounded-md border border-red-500/30 py-1.5 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/10">
                      Disconnect
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  disabled
                  className="w-full rounded-md bg-muted py-2 text-xs font-medium text-muted-foreground"
                  title="Not wired yet"
                >
                  Coming soon
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div className="rounded-lg border border-border bg-card p-5">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Request an Integration</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Don&apos;t see your tool? Let us know and we&apos;ll prioritize it.
        </p>
        <div className="flex gap-3">
          <input
            value={requestText}
            onChange={(e) => setRequestText(e.target.value)}
            placeholder="e.g. Zapier, Airtable, Final Cut Pro..."
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none"
            onKeyDown={(e) => e.key === "Enter" && handleRequest()}
          />
          <button
            onClick={handleRequest}
            className={cn(
              "flex shrink-0 items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors",
              submitted
                ? "bg-emerald-500 text-white"
                : "bg-primary text-primary-foreground hover:bg-primary/90"
            )}
          >
            <Plus className="h-4 w-4" />
            {submitted ? "Submitted!" : "Request"}
          </button>
        </div>
      </div>

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-lg border border-border bg-card/95 backdrop-blur px-4 py-2.5 shadow-lg flex items-center gap-2">
          <CheckCircle className="h-4 w-4 text-emerald-400" />
          <span className="text-sm text-foreground">{toast}</span>
        </div>
      )}
    </div>
  );
}

function YouTubeCard({
  state,
  busy,
  onConnect,
  onDisconnect,
  onRefresh,
}: {
  state: YouTubeState;
  busy: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
  onRefresh: () => void;
}) {
  const isConnected = state.state === "connected";
  const isLoading = state.state === "loading";
  const hasWriteScope =
    state.state === "connected" &&
    state.scopes.includes("https://www.googleapis.com/auth/youtube.force-ssl");

  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-5 transition-colors",
        isConnected ? "border-border" : "border-border hover:border-border/80"
      )}
    >
      <div className="mb-4 flex items-start justify-between">
        <div className="flex items-center gap-3">
          {state.state === "connected" && state.channel.thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={state.channel.thumbnail}
              alt=""
              className="h-10 w-10 shrink-0 rounded-lg"
            />
          ) : (
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-red-600/20 text-sm font-bold text-red-500">
              YT
            </div>
          )}
          <div>
            <p className="font-medium text-foreground">
              {state.state === "connected" && state.channel.channel_title
                ? state.channel.channel_title
                : "YouTube"}
            </p>
            <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-400">
              Platform
            </span>
          </div>
        </div>
        {isConnected && (
          <div className="flex items-center gap-1 text-xs text-emerald-400">
            <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Live
          </div>
        )}
      </div>

      <p className="mb-4 text-sm text-muted-foreground">
        Read channel analytics, pull transcripts, and push metadata to your videos. Required by Publisher and Content Strategist.
      </p>

      {isLoading && (
        <button
          disabled
          className="flex w-full items-center justify-center gap-2 rounded-md border border-border bg-muted/30 py-2 text-xs font-medium text-muted-foreground"
        >
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Checking…
        </button>
      )}

      {state.state === "disconnected" && (
        <button
          onClick={onConnect}
          disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-primary py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Connect YouTube
        </button>
      )}

      {state.state === "error" && (
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs text-red-400">
            <AlertCircle className="h-3.5 w-3.5" />
            {state.message}
          </div>
          <button
            onClick={onRefresh}
            className="w-full rounded-md border border-border py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {isConnected && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <CheckCircle className="h-3.5 w-3.5 text-emerald-400" />
              <span>
                {state.channel.subscriber_count
                  ? `${Intl.NumberFormat("en", { notation: "compact" }).format(state.channel.subscriber_count)} subs`
                  : "Connected"}
              </span>
            </div>
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-[10px] font-medium",
                hasWriteScope
                  ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-400"
              )}
            >
              {hasWriteScope ? "Read + write" : "Read only"}
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={onRefresh}
              disabled={busy}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-border py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
            >
              <RefreshCw className="h-3 w-3" />
              Refresh
            </button>
            <button
              onClick={onDisconnect}
              disabled={busy}
              className="flex-1 rounded-md border border-red-500/30 py-1.5 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-50"
            >
              {busy ? "…" : "Disconnect"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
