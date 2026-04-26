"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle, Loader2, RefreshCw } from "lucide-react";
import { ApprovalCard, type ApprovalRecord } from "@/components/approvals/ApprovalCard";
import { createClient } from "@/lib/supabase/client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type ListState =
  | { state: "loading" }
  | { state: "ready"; approvals: ApprovalRecord[] }
  | { state: "error"; message: string };

export default function ApprovalsPage() {
  const [list, setList] = useState<ListState>({ state: "loading" });
  // Track the in-flight resume so multiple cards can't fire simultaneously
  // while the orchestrator is still streaming the previous decision back.
  const [busyApprovalId, setBusyApprovalId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  /**
   * `withLoading` controls whether we flip back to the "loading" state during
   * the fetch. The initial mount uses useState's "loading" default, so the
   * effect calls this with `withLoading=false` to avoid a synchronous setState
   * inside useEffect (React 19's `react-hooks/set-state-in-effect` rule). The
   * refresh button passes true so the spinner appears mid-session.
   */
  const fetchApprovals = useCallback(async (withLoading: boolean) => {
    if (withLoading) setList({ state: "loading" });
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      const headers: Record<string, string> = session
        ? { Authorization: `Bearer ${session.access_token}` }
        : {};

      const res = await fetch(`${API}/api/approvals`, { headers });
      if (!res.ok) {
        setList({ state: "error", message: `HTTP ${res.status}` });
        return;
      }
      const approvals = (await res.json()) as ApprovalRecord[];
      setList({ state: "ready", approvals });
    } catch (e) {
      setList({ state: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    // No synchronous setState here — fetchApprovals(false) defers all state
    // writes to the post-await branch, satisfying the React 19 lint rule.
    void fetchApprovals(false);
  }, [fetchApprovals]);

  // Auto-dismiss toasts after a couple seconds.
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2200);
    return () => clearTimeout(t);
  }, [toast]);

  /**
   * Drain an SSE response without surfacing tokens to the user — the
   * approvals page isn't a chat. We only care that the stream completed
   * (or surfaced a new `waiting_approval` we should refresh against).
   * Errors get pulled out and shown as a toast.
   */
  async function drainResumeStream(res: Response): Promise<{ rePaused: boolean; err?: string }> {
    const reader = res.body?.getReader();
    const decoder = new TextDecoder();
    if (!reader) return { rePaused: false };

    let buffer = "";
    let rePaused = false;
    let err: string | undefined;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const jsonStr = line.slice(6).trim();
        if (!jsonStr) continue;
        try {
          const event = JSON.parse(jsonStr);
          if (event.type === "waiting_approval") rePaused = true;
          if (event.type === "error") err = event.data?.message || "Unknown error";
        } catch {
          // skip
        }
      }
    }
    return { rePaused, err };
  }

  async function resume(
    approvalId: string,
    decision: "approved" | "rejected",
    feedback?: string
  ) {
    setBusyApprovalId(approvalId);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...(session ? { Authorization: `Bearer ${session.access_token}` } : {}),
      };

      const path =
        decision === "approved"
          ? `/api/approvals/${approvalId}/approve`
          : `/api/approvals/${approvalId}/reject`;
      const body =
        decision === "rejected" && feedback
          ? JSON.stringify({ feedback })
          : undefined;

      const res = await fetch(`${API}${path}`, { method: "POST", headers, body });
      if (!res.ok) {
        setToast(`Resume failed (HTTP ${res.status})`);
        return;
      }
      const { rePaused, err } = await drainResumeStream(res);
      if (err) {
        setToast(`Error: ${err.slice(0, 80)}`);
        return;
      }
      // If the agent re-paused (Brand Manager revise loop, CM revise loop),
      // a NEW approval row exists — refetch to surface it. Otherwise this
      // approval finished and just disappears from the pending list.
      await fetchApprovals(false);
      setToast(
        rePaused
          ? "Sent — agent revised; new approval queued"
          : decision === "approved"
            ? "Approved"
            : "Rejected"
      );
    } catch (e) {
      setToast(`Error: ${(e as Error).message}`);
    } finally {
      setBusyApprovalId(null);
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Approvals</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Review actions agents are waiting on — pitches, replies, anything that touches the outside world.
          </p>
        </div>
        <button
          onClick={() => fetchApprovals(true)}
          disabled={list.state === "loading"}
          className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${list.state === "loading" ? "animate-spin" : ""}`}
          />
          Refresh
        </button>
      </div>

      {list.state === "loading" && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading pending approvals…
        </div>
      )}

      {list.state === "error" && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Couldn&apos;t load approvals: {list.message}
        </div>
      )}

      {list.state === "ready" && list.approvals.length === 0 && (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 p-8 text-center">
          <p className="text-sm font-medium text-foreground">No pending approvals</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Drafts your agents send for your review will show up here.
          </p>
        </div>
      )}

      {list.state === "ready" && list.approvals.length > 0 && (
        <div className="space-y-4">
          {list.approvals.map((a) => (
            <ApprovalCard
              key={a.id}
              approval={a}
              variant="list"
              busy={busyApprovalId !== null && busyApprovalId !== a.id}
              onApprove={(id) => resume(id, "approved")}
              onReject={(id, fb) => resume(id, "rejected", fb)}
            />
          ))}
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-lg border border-border bg-card/95 backdrop-blur px-4 py-2.5 shadow-lg flex items-center gap-2">
          <CheckCircle className="h-4 w-4 text-emerald-400" />
          <span className="text-sm text-foreground">{toast}</span>
        </div>
      )}
    </div>
  );
}
