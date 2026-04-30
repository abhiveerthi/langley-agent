"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  ArrowLeft,
  Briefcase,
  Sparkles,
  AlertCircle,
  Loader2,
  RefreshCw,
  Search,
  PenLine,
  Send,
  Building2,
  Wrench,
  ShieldCheck,
  Mail,
} from "lucide-react";
import { MiniChat } from "@/components/chat/MiniChat";
import { YouTubeStatusPill } from "@/components/integrations/YouTubeStatusPill";
import { KanbanBoard, type KanbanColumnDef } from "@/components/workspace/KanbanBoard";
import { DealCard, type DealRecord } from "@/components/workspace/DealCard";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Re-export the DealCard's type as the local one — we used to define it
// inline; keeping the alias makes the rest of the page diff smaller.
type Deal = DealRecord;

type DealsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; items: Deal[] };

type Approval = {
  id: string;
  action_type: string;
  action_payload: Record<string, unknown>;
  preview: string | null;
  status: string;
  created_at: string;
};

type ApprovalsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; items: Approval[] };

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

// Kanban column definitions — one column per `brand_deals.stage` value.
// Order matches the canonical lifecycle: pitched → replied → negotiating
// → signed, with declined/paused as terminal states on the right.
const DEAL_COLUMNS: KanbanColumnDef[] = [
  { key: "pitched", label: "Pitched", accent: "text-sky-400" },
  { key: "replied", label: "Replied", accent: "text-violet-400" },
  { key: "negotiating", label: "Negotiating", accent: "text-amber-400" },
  { key: "signed", label: "Signed", accent: "text-emerald-400" },
  { key: "declined", label: "Declined", accent: "text-zinc-400" },
  { key: "paused", label: "Paused", accent: "text-zinc-400" },
];

const capabilities: { title: string; body: string; icon: React.ElementType }[] = [
  {
    icon: Search,
    title: "Find sponsor leads",
    body: "Asks Perplexity for brands that match your niche and audience. Returns 5–10 candidates with contact emails when public.",
  },
  {
    icon: Building2,
    title: "Research a target brand",
    body: "Pulls a brand's products, recent campaigns, and creator partnerships so the pitch is specific, not generic.",
  },
  {
    icon: PenLine,
    title: "Draft a tailored pitch",
    body: "Writes a full email — recipient, subject, body — using your media kit (channel stats) and the brand research above.",
  },
  {
    icon: Send,
    title: "Send approved pitches via Resend",
    body: "Once you approve the draft, it sends via Resend and logs the deal as 'pitched' in the pipeline. No auto-sends.",
  },
];

const tools = [
  "find_sponsor_leads",
  "research_brand",
  "get_channel_stats",
  "send_pitch_email",
  "list_active_deals_tool",
];

export default function BrandManagerAgentPage() {
  const [deals, setDeals] = useState<DealsState>({ status: "loading" });
  const [approvals, setApprovals] = useState<ApprovalsState>({ status: "loading" });

  const fetchDeals = useCallback(async () => {
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setDeals({ status: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/brand-manager/deals`, { headers: auth });
      if (!res.ok) {
        setDeals({ status: "error", message: `HTTP ${res.status}` });
        return;
      }
      const items = (await res.json()) as Deal[];
      setDeals({ status: "ok", items });
    } catch (e) {
      setDeals({ status: "error", message: (e as Error).message });
    }
  }, []);

  const fetchApprovals = useCallback(async () => {
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setApprovals({ status: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/approvals`, { headers: auth });
      if (!res.ok) {
        setApprovals({ status: "error", message: `HTTP ${res.status}` });
        return;
      }
      const all = (await res.json()) as Approval[];
      setApprovals({ status: "ok", items: all.filter((a) => a.action_type === "send_email") });
    } catch (e) {
      setApprovals({ status: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    // queueMicrotask defers the initial setState calls past the synchronous
    // effect body — same pattern as the approvals + tasks pages, satisfies
    // React 19's `react-hooks/set-state-in-effect` rule.
    queueMicrotask(() => {
      void fetchDeals();
      void fetchApprovals();
    });
  }, [fetchDeals, fetchApprovals]);

  /**
   * Drag-drop handler. Optimistically flips the deal's stage in local
   * state, then PATCHes the server. On failure, refetches authoritative
   * state to roll back.
   *
   * Within-column reorder is a no-op — brand deals don't have a position
   * column today; ordering within a column is by last_updated_at desc and
   * the PATCH bumps that automatically. KanbanBoard's
   * `sameRelativePosition` short-circuits no-op moves so we never see
   * those events.
   */
  const handleMove = useCallback(
    async (dealId: string, toStage: string) => {
      // Optimistic update.
      setDeals((prev) => {
        if (prev.status !== "ok") return prev;
        return {
          status: "ok",
          items: prev.items.map((d) =>
            d.id === dealId
              ? { ...d, stage: toStage as Deal["stage"], last_updated_at: new Date().toISOString() }
              : d,
          ),
        };
      });

      try {
        const auth = await authHeader();
        const res = await fetch(`${API}/api/brand-manager/deals/${dealId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...auth },
          body: JSON.stringify({ stage: toStage }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch {
        // Rollback to authoritative state.
        await fetchDeals();
      }
    },
    [fetchDeals],
  );

  const dealCount = deals.status === "ok" ? deals.items.length : 0;
  const signedCount = deals.status === "ok" ? deals.items.filter((d) => d.stage === "signed").length : 0;
  const pendingPitches = approvals.status === "ok" ? approvals.items.length : 0;

  return (
    <div className="flex h-full min-h-0">
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <div>
          <Link
            href="/app/agents"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3 transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Agents
          </Link>
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-amber-500/10 border border-amber-500/20">
              <Briefcase className="h-5 w-5 text-amber-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Brand Manager</h1>
              <p className="text-sm text-muted-foreground">
                Drafts sponsor outreach and tailored pitches, tracks deal stages. Sends via Resend — gated by your approval.
              </p>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-sm font-medium text-emerald-400">Active</span>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          <Stat label="Active deals" value={dealCount.toString()} />
          <Stat label="Signed" value={signedCount.toString()} />
          <Stat label="Pending pitches" value={pendingPitches.toString()} />
        </div>

        {/* Capabilities */}
        <Section title="What the Brand Manager does" subtitle="Research and drafting are read-only. Sending an email always pauses for your approval first.">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {capabilities.map((c) => (
              <CapabilityCard key={c.title} {...c} />
            ))}
          </div>
        </Section>

        {/* Approval flow */}
        <Section title="Approval flow" subtitle="Pitches are drafted, extracted into recipient/subject/body, and held for your sign-off.">
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground mb-3">
              <ShieldCheck className="h-4 w-4 text-amber-400" />
              Send a pitch
            </div>
            <ol className="space-y-2 text-sm text-muted-foreground">
              <li className="flex gap-2.5"><span className="text-amber-400 font-mono">1.</span><span>You ask: <span className="text-foreground">&quot;draft a pitch to Magpul&quot;</span></span></li>
              <li className="flex gap-2.5"><span className="text-amber-400 font-mono">2.</span><span>It pulls your media kit, researches Magpul, and drafts an email tailored to their products + your audience.</span></li>
              <li className="flex gap-2.5"><span className="text-amber-400 font-mono">3.</span><span>Pauses at the approval gate — you see the To / Subject / Body in chat or Slack.</span></li>
              <li className="flex gap-2.5"><span className="text-amber-400 font-mono">4.</span><span>Approve → Resend sends it, deal logged as <code className="font-mono text-foreground">pitched</code>. Reject with feedback → revise + re-pause.</span></li>
            </ol>
          </div>
        </Section>

        {/* Tools */}
        <Section title="Tools available" subtitle="The functions the agent can call.">
          <div className="flex flex-wrap gap-1.5">
            {tools.map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/30 px-2 py-1 text-[11px] font-mono text-muted-foreground"
              >
                <Wrench className="h-3 w-3 text-amber-400" />
                {t}
              </span>
            ))}
          </div>
        </Section>

        {/* Deal pipeline — Kanban */}
        <Section
          title="Deal pipeline"
          subtitle="Drag a deal between columns to update its stage. Pitched rows are auto-logged when an approved pitch sends; everything past that is manual today (inbox-driven stage updates are a future feature)."
        >
          <DealsBoard state={deals} onRefresh={fetchDeals} onMove={handleMove} />
        </Section>
      </div>

      <div className="w-80 shrink-0 border-l border-border bg-card/50 overflow-y-auto p-5 space-y-6">
        <YouTubeStatusPill heading="Channel (for media kit)" />

        <div className="rounded-lg border border-border bg-muted/20 p-4 text-xs text-muted-foreground space-y-2">
          <div className="flex items-center gap-2 text-foreground font-medium">
            <Mail className="h-3.5 w-3.5 text-amber-400" />
            Resend
          </div>
          <p>
            Pitches send via Resend using a server-side API key — no per-user OAuth needed. If sends are failing, the API key on the backend is the first place to check.
          </p>
        </div>

        <div className="rounded-lg border border-border bg-muted/20 p-4 text-xs text-muted-foreground space-y-2">
          <div className="flex items-center gap-2 text-foreground font-medium">
            <Sparkles className="h-3.5 w-3.5 text-amber-400" />
            How to use it
          </div>
          <p>
            Try <span className="text-foreground font-medium">&quot;find me 5 sponsor leads in the AI tools space&quot;</span> or{" "}
            <span className="text-foreground font-medium">&quot;draft a pitch to Notion&quot;</span>.
          </p>
        </div>
      </div>

      <MiniChat agentSlug="brand-manager" agentName="Brand Manager" />
    </div>
  );
}

// ── Subcomponents ─────────────────────────────────────────────────────────

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-2xl font-bold text-foreground">{value}</div>
      <div className="text-xs text-muted-foreground mt-1">{label}</div>
    </div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {subtitle && <p className="text-xs text-muted-foreground mt-0.5 mb-3">{subtitle}</p>}
      {!subtitle && <div className="mb-3" />}
      {children}
    </div>
  );
}

function CapabilityCard({ icon: Icon, title, body }: { icon: React.ElementType; title: string; body: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-amber-500/10 border border-amber-500/20">
        <Icon className="h-4 w-4 text-amber-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="text-xs text-muted-foreground mt-1 leading-relaxed">{body}</div>
      </div>
    </div>
  );
}

/**
 * Kanban-board variant of DealsList. Same loading/error/empty branches,
 * but the success state hands off to the generic `<KanbanBoard>` for
 * drag-drop column moves. The `position` field on each item is derived
 * from `last_updated_at` — brand deals don't have an explicit position
 * column (within-column ordering is by recency), but `KanbanBoard`
 * needs a `position: number` to sort by, so we map the timestamp into
 * a negative number (newer = smaller = top).
 */
function DealsBoard({
  state,
  onRefresh,
  onMove,
}: {
  state: DealsState;
  onRefresh: () => void;
  onMove: (dealId: string, toStage: string) => void;
}) {
  if (state.status === "loading") {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
        <Loader2 className="h-6 w-6 text-muted-foreground animate-spin mx-auto mb-2" />
        <div className="text-sm text-muted-foreground">Loading deals…</div>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-5">
        <div className="flex items-center gap-2 mb-2">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-sm font-medium text-red-400">Couldn&apos;t load deals</span>
        </div>
        <div className="text-xs text-muted-foreground mb-3">{state.message}</div>
        <button
          onClick={onRefresh}
          className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </button>
      </div>
    );
  }
  if (state.items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
        <div className="text-sm text-foreground font-medium">No deals yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Once you approve a pitch, the deal will land here as <code className="font-mono">pitched</code>.
        </div>
      </div>
    );
  }

  // Map each deal into a KanbanItem. `status` = stage, `position` = the
  // negated timestamp so newer deals sort to the top of their column.
  const items = state.items.map((d) => ({
    ...d,
    status: d.stage,
    position: -new Date(d.last_updated_at).getTime(),
  }));

  return (
    <KanbanBoard
      columns={DEAL_COLUMNS}
      items={items}
      onMove={(itemId, toColumnKey) => onMove(itemId, toColumnKey)}
      renderCard={(item, { isDragging }) => (
        <DealCard
          key={item.id}
          // Strip the KanbanItem-only fields (status, position) — the
          // card needs the original DealRecord shape.
          deal={item as DealRecord}
          isDragging={isDragging}
        />
      )}
    />
  );
}
