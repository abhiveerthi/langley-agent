"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Plug } from "lucide-react";
import { createClient } from "@/lib/supabase/client";

type Status =
  | { state: "loading" }
  | { state: "disconnected" }
  | {
      state: "connected";
      user: { username?: string; name?: string; profile_image_url?: string };
      scopes: string[];
    }
  | { state: "error"; message: string };

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function TwitterStatusPill({ heading = "X / Twitter" }: { heading?: string }) {
  const [status, setStatus] = useState<Status>({ state: "loading" });

  const fetchStatus = useCallback(async () => {
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) {
        setStatus({ state: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/integrations/twitter/status`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) {
        setStatus({ state: "error", message: `HTTP ${res.status}` });
        return;
      }
      const data = await res.json();
      if (!data.connected) {
        setStatus({ state: "disconnected" });
        return;
      }
      setStatus({ state: "connected", user: data.user || {}, scopes: data.scopes || [] });
    } catch (e) {
      setStatus({ state: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return (
    <div>
      <h3 className="text-sm font-semibold text-foreground mb-3">{heading}</h3>

      {status.state === "loading" && (
        <div className="rounded-md border border-border bg-muted/20 px-3 py-3 flex items-center gap-3">
          <Loader2 className="h-4 w-4 text-muted-foreground animate-spin" />
          <span className="text-sm text-muted-foreground">Checking connection…</span>
        </div>
      )}

      {status.state === "disconnected" && (
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

      {status.state === "error" && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 px-3 py-3">
          <div className="flex items-center gap-2 mb-1">
            <AlertCircle className="h-4 w-4 text-red-400" />
            <span className="text-sm font-medium text-red-400">Connection error</span>
          </div>
          <div className="text-xs text-muted-foreground mb-2">{status.message}</div>
          <button onClick={fetchStatus} className="text-xs text-primary hover:underline">
            Retry
          </button>
        </div>
      )}

      {status.state === "connected" && (
        <div className="rounded-md border border-border bg-muted/20 px-3 py-3 flex items-center gap-3">
          <div className="h-9 w-9 shrink-0 rounded-full bg-foreground/10 flex items-center justify-center p-1.5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/integrations/x.svg" alt="" className="h-full w-full object-contain" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-foreground truncate">X (Twitter)</div>
            <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5 truncate">
              {status.user.profile_image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={status.user.profile_image_url} alt="" className="h-3.5 w-3.5 rounded-full shrink-0" />
              )}
              <span className="truncate">
                {status.user.username
                  ? `@${status.user.username}`
                  : status.user.name || "Connected"}
              </span>
            </div>
          </div>
          <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
        </div>
      )}
    </div>
  );
}
