"use client";

import Link from "next/link";
import { useCallback } from "react";
import { AlertCircle, CheckCircle2, Loader2, Plug } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { useStaleWhileRevalidate } from "@/lib/swr";

type StatusResponse =
  | { connected: false }
  | {
      connected: true;
      channel?: { channel_title?: string; thumbnail?: string; subscriber_count?: number };
      scopes?: string[];
    };

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// localStorage key for the SWR layer. The pill is global per user; no need
// to scope on org id today (single-org-per-user model).
const CACHE_KEY = "integrations.youtube.status";

async function fetchYouTubeStatus(): Promise<StatusResponse> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) throw new Error("Not signed in");
  const res = await fetch(`${API}/api/integrations/youtube/status`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as StatusResponse;
}

export function YouTubeStatusPill({ heading = "YouTube" }: { heading?: string }) {
  // Inline arrow keeps the React 19 `react-hooks/use-memo` lint happy.
  // The hook itself uses a ref internally so re-renders don't cascade.
  const fetcher = useCallback(() => fetchYouTubeStatus(), []);
  const { data, error, isLoading, refresh } = useStaleWhileRevalidate<StatusResponse>(
    CACHE_KEY,
    fetcher,
  );

  return (
    <div>
      <h3 className="text-sm font-semibold text-foreground mb-3">{heading}</h3>

      {/* Loading is only true on the very first ever mount with no cache.
          On every subsequent mount the cached value renders instantly. */}
      {isLoading && (
        <div className="rounded-md border border-border bg-muted/20 px-3 py-3 flex items-center gap-3">
          <Loader2 className="h-4 w-4 text-muted-foreground animate-spin" />
          <span className="text-sm text-muted-foreground">Checking connection…</span>
        </div>
      )}

      {!isLoading && error && !data && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 px-3 py-3">
          <div className="flex items-center gap-2 mb-1">
            <AlertCircle className="h-4 w-4 text-red-400" />
            <span className="text-sm font-medium text-red-400">Connection error</span>
          </div>
          <div className="text-xs text-muted-foreground mb-2">{error.message}</div>
          <button onClick={() => void refresh()} className="text-xs text-primary hover:underline">
            Retry
          </button>
        </div>
      )}

      {!isLoading && data && data.connected === false && (
        <Link
          href="/app/integrations"
          className="flex items-center gap-3 rounded-md border border-dashed border-border bg-muted/10 px-3 py-3 hover:border-sky-500/40 hover:bg-sky-500/5 transition-colors"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-dashed border-border text-muted-foreground">
            <Plug className="h-4 w-4" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-foreground">Not connected</div>
            <div className="text-xs text-sky-400 mt-0.5">Connect in Integrations →</div>
          </div>
        </Link>
      )}

      {!isLoading && data && data.connected === true && (
        <div className="rounded-md border border-border bg-muted/20 px-3 py-3 flex items-center gap-3">
          <div className="h-9 w-9 shrink-0 rounded-full bg-red-600/20 flex items-center justify-center p-1.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/integrations/youtube.svg" alt="" className="h-full w-full object-contain" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-foreground truncate">YouTube</div>
            <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5 truncate">
              {data.channel?.thumbnail && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={data.channel.thumbnail} alt="" className="h-3.5 w-3.5 rounded-full shrink-0" />
              )}
              <span className="truncate">
                {data.channel?.channel_title || "Your Channel"}
                {data.channel?.subscriber_count
                  ? ` · ${Intl.NumberFormat("en", { notation: "compact" }).format(data.channel.subscriber_count)} subs`
                  : ""}
              </span>
            </div>
          </div>
          <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
        </div>
      )}
    </div>
  );
}
