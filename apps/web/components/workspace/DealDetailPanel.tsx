"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Building2, ExternalLink, Loader2, Mail, X, AlertCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const STAGES = ["pitched", "replied", "negotiating", "signed", "declined", "paused"] as const;
type Stage = (typeof STAGES)[number];

type Deal = {
  id: string;
  brand_name: string;
  recipient: string | null;
  subject: string | null;
  stage: Stage;
  external_message_id: string | null;
  notes: string | null;
  pitched_at: string | null;
  last_updated_at: string;
};

type LinkedTask = {
  id: string;
  title: string;
  status: string;
  priority: string;
  due_at: string | null;
  agents?: { name: string; slug: string; icon: string | null } | null;
};

type DetailResponse = { deal: Deal; tasks: LinkedTask[] };

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; deal: Deal; tasks: LinkedTask[] };

const stageStyles: Record<Stage, string> = {
  pitched: "bg-sky-500/10 text-sky-400 border-sky-500/20",
  replied: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  negotiating: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  signed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  declined: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
  paused: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
};

const priorityColor: Record<string, string> = {
  high: "text-red-400",
  medium: "text-amber-400",
  low: "text-muted-foreground",
};

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

interface DealDetailPanelProps {
  /** When null, the panel renders nothing — controlled by the parent. */
  dealId: string | null;
  onClose: () => void;
  /** Called after a stage / notes update so the parent can refetch the
   *  deals list and reflect the new stage on the dashboard. */
  onChange?: () => void;
}

export function DealDetailPanel({ dealId, onClose, onChange }: DealDetailPanelProps) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const [savingStage, setSavingStage] = useState(false);
  const [notesDraft, setNotesDraft] = useState("");
  const [savingNotes, setSavingNotes] = useState(false);

  const fetchDetail = useCallback(async (id: string) => {
    setState({ kind: "loading" });
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setState({ kind: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/brand-manager/deals/${id}`, { headers: auth });
      if (!res.ok) {
        setState({ kind: "error", message: `HTTP ${res.status}` });
        return;
      }
      const body = (await res.json()) as DetailResponse;
      setState({ kind: "ok", deal: body.deal, tasks: body.tasks });
      setNotesDraft(body.deal.notes ?? "");
    } catch (e) {
      setState({ kind: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    if (!dealId) {
      setState({ kind: "idle" });
      setNotesDraft("");
      return;
    }
    void fetchDetail(dealId);
  }, [dealId, fetchDetail]);

  // Close on Escape — keeps the panel feeling like a proper overlay.
  useEffect(() => {
    if (!dealId) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dealId, onClose]);

  async function patchDeal(updates: { stage?: Stage; notes?: string }) {
    if (state.kind !== "ok") return;
    const auth = await authHeader();
    if (!auth.Authorization) return;
    const res = await fetch(`${API}/api/brand-manager/deals/${state.deal.id}`, {
      method: "PATCH",
      headers: { ...auth, "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const updated = (await res.json()) as Deal;
    setState((prev) => (prev.kind === "ok" ? { ...prev, deal: updated } : prev));
    onChange?.();
  }

  async function handleStageChange(next: Stage) {
    if (state.kind !== "ok" || next === state.deal.stage) return;
    setSavingStage(true);
    try {
      await patchDeal({ stage: next });
    } catch {
      // Best-effort — leave the previous stage if the PATCH fails. A toast
      // system would surface this; for now the UI just snaps back on the
      // next refetch.
    } finally {
      setSavingStage(false);
    }
  }

  async function handleNotesSave() {
    if (state.kind !== "ok") return;
    if ((state.deal.notes ?? "") === notesDraft) return;
    setSavingNotes(true);
    try {
      await patchDeal({ notes: notesDraft });
    } catch {
      // ignore — same rationale as stage save.
    } finally {
      setSavingNotes(false);
    }
  }

  if (!dealId) return null;

  return (
    <>
      {/* Backdrop — click to close. Lower z than the panel so the panel
          sits on top, but still high enough to cover the dashboard. */}
      <div
        onClick={onClose}
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-label="Deal details"
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[480px] flex-col border-l border-border bg-card shadow-2xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-border p-5">
          <div className="flex items-start gap-3 min-w-0">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-amber-500/10 border border-amber-500/20">
              <Building2 className="h-5 w-5 text-amber-400" />
            </div>
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold text-foreground">
                {state.kind === "ok" ? state.deal.brand_name : "Deal details"}
              </h2>
              {state.kind === "ok" && state.deal.subject && (
                <p className="mt-0.5 truncate text-xs text-muted-foreground">
                  {state.deal.subject}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {state.kind === "loading" && (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {state.kind === "error" && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4">
              <div className="flex items-center gap-2 text-sm text-red-400">
                <AlertCircle className="h-4 w-4" />
                Couldn&apos;t load deal — {state.message}
              </div>
            </div>
          )}

          {state.kind === "ok" && (
            <>
              {/* Pitch metadata */}
              <section className="rounded-lg border border-border bg-muted/20 p-4 text-sm space-y-2">
                <div className="flex items-center gap-2 text-foreground font-medium">
                  <Mail className="h-3.5 w-3.5 text-amber-400" />
                  Pitch
                </div>
                {state.deal.recipient && (
                  <div className="text-xs">
                    <span className="text-muted-foreground">To: </span>
                    <span className="text-foreground">{state.deal.recipient}</span>
                  </div>
                )}
                {state.deal.subject && (
                  <div className="text-xs">
                    <span className="text-muted-foreground">Subject: </span>
                    <span className="text-foreground">{state.deal.subject}</span>
                  </div>
                )}
                {state.deal.pitched_at && (
                  <div className="text-xs text-muted-foreground">
                    Pitched {new Date(state.deal.pitched_at).toLocaleString()}
                  </div>
                )}
              </section>

              {/* Stage selector */}
              <section className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/80">
                  Stage
                </label>
                <div className="flex items-center gap-2">
                  <select
                    value={state.deal.stage}
                    onChange={(e) => handleStageChange(e.target.value as Stage)}
                    disabled={savingStage}
                    className={cn(
                      "rounded-md border bg-background px-3 py-1.5 text-sm font-medium focus:border-primary/50 focus:outline-none disabled:opacity-50",
                      stageStyles[state.deal.stage],
                    )}
                  >
                    {STAGES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                  {savingStage && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
                </div>
              </section>

              {/* Notes */}
              <section className="space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/80">
                  Notes
                </label>
                <textarea
                  value={notesDraft}
                  onChange={(e) => setNotesDraft(e.target.value)}
                  onBlur={handleNotesSave}
                  rows={4}
                  placeholder="Left voicemail Tuesday. Asked for media kit…"
                  className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none"
                />
                <p className="text-[11px] text-muted-foreground">
                  {savingNotes ? "Saving…" : "Saves on blur."}
                </p>
              </section>

              {/* Linked tasks */}
              <section className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/80">
                    Linked tasks <span className="text-muted-foreground/60 font-normal normal-case">· {state.tasks.length}</span>
                  </label>
                  <Link
                    href={`/app/tasks?deal_id=${state.deal.id}`}
                    className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                  >
                    Open in workspace
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                </div>
                {state.tasks.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-border bg-muted/10 px-4 py-6 text-center text-xs text-muted-foreground">
                    No tasks linked yet. Brand Manager auto-creates a follow-up after a pitch sends.
                  </div>
                ) : (
                  <ul className="space-y-2">
                    {state.tasks.map((t) => (
                      <li
                        key={t.id}
                        className="rounded-lg border border-border bg-card/60 p-3 text-sm"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="text-foreground">{t.title}</div>
                            <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                              <span className={cn("uppercase", priorityColor[t.priority] ?? "")}>
                                {t.priority}
                              </span>
                              <span>·</span>
                              <span>{t.status.replace(/_/g, " ")}</span>
                              {t.agents?.name && (
                                <>
                                  <span>·</span>
                                  <span>{t.agents.name}</span>
                                </>
                              )}
                              {t.due_at && (
                                <>
                                  <span>·</span>
                                  <span>due {new Date(t.due_at).toLocaleDateString()}</span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
