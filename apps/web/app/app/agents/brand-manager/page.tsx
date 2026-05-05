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
import { cn } from "@/lib/utils";
import { MiniChat } from "@/components/chat/MiniChat";
import { YouTubeStatusPill } from "@/components/integrations/YouTubeStatusPill";
import { DealDetailPanel } from "@/components/workspace/DealDetailPanel";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Deal = {
  id: string;
  brand_name: string;
  recipient: string | null;
  subject: string | null;
  stage: "pitched" | "replied" | "negotiating" | "signed" | "declined" | "paused";
  external_message_id: string | null;
  notes: string | null;
  pitched_at: string | null;
  last_updated_at: string;
};

// One state object instead of two — `deals` and `pending_pitches` come from
// the same endpoint now (`GET /brand-manager/dashboard`), so they load and
// fail together. Single round trip = single loading skeleton.
type DashboardState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; deals: Deal[]; pendingPitches: number };

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const hours = diff / 3600_000;
  if (hours < 1) return "Just now";
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  const days = hours / 24;
  if (days < 7) return `${Math.floor(days)}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return new Date(iso).toLocaleDateString();
}

const stageStyles: Record<Deal["stage"], string> = {
  pitched: "bg-sky-500/10 text-sky-400 border-sky-500/20",
  replied: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  negotiating: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  signed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  declined: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
  paused: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
};

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

const stageBuckets: { label: string; stages: Deal["stage"][] }[] = [
  { label: "Pitched", stages: ["pitched"] },
  { label: "In motion", stages: ["replied", "negotiating"] },
  { label: "Signed", stages: ["signed"] },
  { label: "Closed", stages: ["declined", "paused"] },
];

export default function BrandManagerAgentPage() {
  const [dashboard, setDashboard] = useState<DashboardState>({ status: "loading" });
  // Deal-detail drawer state. `selectedDealId !== null` opens the panel,
  // and the panel's onChange refetches the dashboard so stage edits in the
  // drawer reflect on the cards immediately.
  const [selectedDealId, setSelectedDealId] = useState<string | null>(null);

  const fetchDashboard = useCallback(async () => {
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setDashboard({ status: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/brand-manager/dashboard`, { headers: auth });
      if (!res.ok) {
        setDashboard({ status: "error", message: `HTTP ${res.status}` });
        return;
      }
      const body = (await res.json()) as { deals: Deal[]; pending_pitches: number };
      setDashboard({
        status: "ok",
        deals: body.deals,
        pendingPitches: body.pending_pitches,
      });
    } catch (e) {
      setDashboard({ status: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void fetchDashboard();
    });
  }, [fetchDashboard]);

  const dealCount = dashboard.status === "ok" ? dashboard.deals.length : 0;
  const signedCount = dashboard.status === "ok"
    ? dashboard.deals.filter((d) => d.stage === "signed").length
    : 0;
  const pendingPitches = dashboard.status === "ok" ? dashboard.pendingPitches : 0;

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

        {/* Deal pipeline */}
        <Section title="Deal pipeline" subtitle="Click any deal to update its stage, leave notes, or see linked follow-up tasks.">
          <DealsList
            state={dashboard}
            onRefresh={fetchDashboard}
            onSelect={(id) => setSelectedDealId(id)}
          />
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

      <DealDetailPanel
        dealId={selectedDealId}
        onClose={() => setSelectedDealId(null)}
        onChange={fetchDashboard}
      />
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

function DealsList({
  state,
  onRefresh,
  onSelect,
}: {
  state: DashboardState;
  onRefresh: () => void;
  onSelect: (dealId: string) => void;
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
  if (state.deals.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
        <div className="text-sm text-foreground font-medium">No deals yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Once you approve a pitch, the deal will land here as <code className="font-mono">pitched</code>.
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-5">
      {stageBuckets.map((bucket) => {
        const inBucket = state.deals.filter((d) => bucket.stages.includes(d.stage));
        if (inBucket.length === 0) return null;
        return (
          <div key={bucket.label}>
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/80 mb-2">
              {bucket.label} <span className="text-muted-foreground/60 font-normal">· {inBucket.length}</span>
            </div>
            <div className="space-y-2">
              {inBucket.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => onSelect(d.id)}
                  className="w-full rounded-lg border border-border bg-card p-3.5 text-left transition-colors hover:bg-accent/40 hover:border-amber-500/30 focus:border-amber-500/40 focus:outline-none"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-amber-500/10">
                        <Building2 className="h-4 w-4 text-amber-400" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-foreground">{d.brand_name}</div>
                        {d.subject && (
                          <div className="text-xs text-muted-foreground mt-0.5 truncate">{d.subject}</div>
                        )}
                        <div className="flex items-center gap-3 mt-1.5 text-[11px] text-muted-foreground">
                          {d.recipient && <span className="truncate">{d.recipient}</span>}
                          <span>{relativeTime(d.last_updated_at)}</span>
                        </div>
                      </div>
                    </div>
                    <span className={cn("rounded-full border px-2.5 py-0.5 text-[11px] font-medium shrink-0", stageStyles[d.stage])}>
                      {d.stage}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
