"use client";

import { useState } from "react";
import { Check, Loader2, X, ShieldCheck } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

type Status = "approved" | "rejected" | undefined;

interface ApprovalCardInChannelProps {
  channelId: string;
  approvalId: string;
  /** When set, the card renders the resolved variant (no buttons). */
  status: Status;
  /** Pretty-printed name of whoever decided, or null when unresolved. */
  reviewedByLabel: string | null;
  /** The dispatching agent's display name — drives the card header. */
  agentName: string | null;
  /** Body of the parent message, used as the action description. */
  body: string;
}

/**
 * Inline approval card embedded in a `channel_messages` row whose
 * `metadata.kind === "approval"`. Drives the existing approval flow
 * via the channel-context endpoints — the buttons POST to
 * `/api/channels/{channelId}/approvals/{approvalId}/{approve,reject}`,
 * which:
 *   1. Syncronously UPDATEs this row's metadata so the realtime UPDATE
 *      event swaps the buttons for the "approved by @sean" tag.
 *   2. Backgrounds the actual agent resume (drains the stream, posts
 *      the agent's continuation as a fresh channel message).
 *
 * That two-step design keeps the click-to-feedback latency under a
 * second even when the agent resume itself takes 5-10s of LLM time.
 */
export function ApprovalCardInChannel({
  channelId,
  approvalId,
  status,
  reviewedByLabel,
  agentName,
  body,
}: ApprovalCardInChannelProps) {
  const [submitting, setSubmitting] = useState<null | "approve" | "reject">(null);
  const [error, setError] = useState<string | null>(null);

  // Resolved state — render the "approved/rejected by @x" tag and bail.
  if (status === "approved" || status === "rejected") {
    return (
      <div
        className={cn(
          "mt-2 flex items-center gap-2 rounded-md border px-3 py-2 text-xs",
          status === "approved"
            ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-400"
            : "border-zinc-500/30 bg-zinc-500/10 text-muted-foreground",
        )}
      >
        {status === "approved" ? (
          <Check className="h-3.5 w-3.5" />
        ) : (
          <X className="h-3.5 w-3.5" />
        )}
        <span className="font-medium uppercase tracking-wider">
          {status === "approved" ? "Approved" : "Rejected"}
        </span>
        {reviewedByLabel && (
          <span className="text-muted-foreground">
            by {reviewedByLabel}
          </span>
        )}
      </div>
    );
  }

  async function decide(decision: "approve" | "reject") {
    if (submitting) return;
    setSubmitting(decision);
    setError(null);
    try {
      const auth = await authHeader();
      const res = await fetch(
        `${API}/api/channels/${channelId}/approvals/${approvalId}/${decision}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...auth },
          // Reject feedback stays empty in v1 — the feature exists in
          // the API contract for when we add a "what would you change?"
          // input below the buttons.
          body: decision === "reject" ? JSON.stringify({}) : undefined,
        },
      );
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        setError(detail?.detail ?? `HTTP ${res.status}`);
        return;
      }
      // Don't optimistically mutate state — the realtime UPDATE handler
      // in ChannelView will patch this card the moment the server's
      // synchronous metadata UPDATE lands. Keeps the source of truth
      // server-side.
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-amber-400">
        <ShieldCheck className="h-3.5 w-3.5" />
        Action needs approval
        {agentName && (
          <span className="text-muted-foreground font-normal">
            · from {agentName}
          </span>
        )}
      </div>
      <p className="mb-3 text-sm text-foreground">{body}</p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void decide("approve")}
          disabled={!!submitting}
          className="inline-flex items-center gap-1.5 rounded-md bg-emerald-500/15 border border-emerald-500/30 px-3 py-1.5 text-xs font-medium text-emerald-400 hover:bg-emerald-500/25 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting === "approve" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Check className="h-3 w-3" />
          )}
          Approve
        </button>
        <button
          type="button"
          onClick={() => void decide("reject")}
          disabled={!!submitting}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting === "reject" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <X className="h-3 w-3" />
          )}
          Reject
        </button>
      </div>
      {error && (
        <p className="mt-2 text-xs text-red-400">
          Couldn&apos;t submit — {error}
        </p>
      )}
    </div>
  );
}
