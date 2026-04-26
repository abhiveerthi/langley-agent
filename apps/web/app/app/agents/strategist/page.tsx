"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  ArrowLeft,
  Compass,
  Sparkles,
  AlertCircle,
  Loader2,
  RefreshCw,
  Lightbulb,
  TrendingUp,
  Users,
  FileText,
  Wrench,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MiniChat } from "@/components/chat/MiniChat";
import { YouTubeStatusPill } from "@/components/integrations/YouTubeStatusPill";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Surface shape mirrors WeeklyBrief in packages/agents/strategist/agent.py
type VideoIdea = {
  title: string;
  hook: string;
  why_now: string;
  confidence: "high" | "medium" | "low";
  rationale: string;
  citations: string[];
};

type Brief = {
  id: string;
  headline: string;
  ideas: VideoIdea[];
  created_at: string;
  thread_id: string | null;
};

type BriefsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; items: Brief[] };

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

const confidenceStyles: Record<VideoIdea["confidence"], string> = {
  high: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  medium: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  low: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
};

const capabilities: { title: string; body: string; icon: React.ElementType }[] = [
  {
    icon: Lightbulb,
    title: "Compose a weekly brief",
    body: "Pulls your channel analytics + niche trends, ranks 3–5 video ideas with hooks, citations, and confidence scores.",
  },
  {
    icon: TrendingUp,
    title: "Pull niche & competitor trends",
    body: "Uses live web search to surface what's working in your niche right now — competitor titles, audience demand, fresh angles.",
  },
  {
    icon: FileText,
    title: "Outline scripts & hooks",
    body: "Once you pick an idea, asks for outline depth and writes a script frame + hook variants in your voice.",
  },
  {
    icon: Users,
    title: "Reads peer-agent context",
    body: "Sees the latest Publisher package and Brand Manager deals so a new brief builds on what's actually shipping.",
  },
];

const tools = [
  "get_channel_stats",
  "get_recent_video_performance",
  "search_niche_trends",
  "search_competitor_videos",
  "get_channel_analytics_overview",
  "get_video_analytics_performance",
  "get_traffic_sources",
];

export default function StrategistAgentPage() {
  const [briefs, setBriefs] = useState<BriefsState>({ status: "loading" });

  const fetchBriefs = useCallback(async () => {
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setBriefs({ status: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/strategist/briefs`, { headers: auth });
      if (!res.ok) {
        setBriefs({ status: "error", message: `HTTP ${res.status}` });
        return;
      }
      const items = (await res.json()) as Brief[];
      setBriefs({ status: "ok", items });
    } catch (e) {
      setBriefs({ status: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    fetchBriefs();
  }, [fetchBriefs]);

  const briefsCount = briefs.status === "ok" ? briefs.items.length : 0;
  const ideasCount = briefs.status === "ok"
    ? briefs.items.reduce((sum, b) => sum + (b.ideas?.length ?? 0), 0)
    : 0;
  const lastBriefAt = briefs.status === "ok" && briefs.items.length > 0
    ? relativeTime(briefs.items[0].created_at)
    : "—";

  return (
    <div className="flex h-full min-h-0">
      {/* Main */}
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
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-500/10 border border-indigo-500/20">
              <Compass className="h-5 w-5 text-indigo-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Strategist</h1>
              <p className="text-sm text-muted-foreground">
                Decides what to make next. Pulls channel analytics + niche trends, ranks video ideas, drafts hooks and outlines.
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
          <Stat label="Briefs" value={briefsCount.toString()} />
          <Stat label="Ranked Ideas" value={ideasCount.toString()} />
          <Stat label="Last brief" value={lastBriefAt} />
        </div>

        {/* What I do */}
        <Section title="What the Strategist does" subtitle="Ask anything in chat — it'll route the request to the right step.">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {capabilities.map((c) => (
              <CapabilityCard key={c.title} {...c} />
            ))}
          </div>
        </Section>

        {/* Tools */}
        <Section title="Tools available" subtitle="The actual functions the agent can call. Useful when you want to nudge it toward a specific lookup.">
          <div className="flex flex-wrap gap-1.5">
            {tools.map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/30 px-2 py-1 text-[11px] font-mono text-muted-foreground"
              >
                <Wrench className="h-3 w-3 text-indigo-400" />
                {t}
              </span>
            ))}
          </div>
        </Section>

        {/* Briefs */}
        <Section title="Recent briefs" subtitle="Past WeeklyBriefs the Strategist has composed for this org.">
          <BriefsList state={briefs} onRefresh={fetchBriefs} />
        </Section>
      </div>

      {/* Right rail */}
      <div className="w-80 shrink-0 border-l border-border bg-card/50 overflow-y-auto p-5 space-y-6">
        <YouTubeStatusPill heading="Channel Connected" />

        <div className="rounded-lg border border-border bg-muted/20 p-4 text-xs text-muted-foreground space-y-2">
          <div className="flex items-center gap-2 text-foreground font-medium">
            <Sparkles className="h-3.5 w-3.5 text-indigo-400" />
            How to use it
          </div>
          <p>
            Open chat below and try <span className="text-foreground font-medium">&quot;give me this week&apos;s brief&quot;</span>{" "}
            or <span className="text-foreground font-medium">&quot;outline a script for the AI tools idea&quot;</span>.
          </p>
          <p>
            The Strategist needs your YouTube channel connected to read analytics. Web search for niche trends works without any extra connection.
          </p>
        </div>
      </div>

      <MiniChat agentSlug="strategist" agentName="Strategist" />
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
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-indigo-500/10 border border-indigo-500/20">
        <Icon className="h-4 w-4 text-indigo-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="text-xs text-muted-foreground mt-1 leading-relaxed">{body}</div>
      </div>
    </div>
  );
}

function BriefsList({ state, onRefresh }: { state: BriefsState; onRefresh: () => void }) {
  if (state.status === "loading") {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
        <Loader2 className="h-6 w-6 text-muted-foreground animate-spin mx-auto mb-2" />
        <div className="text-sm text-muted-foreground">Loading briefs…</div>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-5">
        <div className="flex items-center gap-2 mb-2">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-sm font-medium text-red-400">Couldn&apos;t load briefs</span>
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
        <div className="text-sm text-foreground font-medium">No briefs yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Ask the Strategist for <span className="text-foreground">&quot;this week&apos;s brief&quot;</span> in chat to compose your first one.
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {state.items.map((b) => (
        <BriefCard key={b.id} brief={b} />
      ))}
    </div>
  );
}

function BriefCard({ brief }: { brief: Brief }) {
  const [expanded, setExpanded] = useState(false);
  const ideas = brief.ideas ?? [];
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-4 mb-2">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-500/10">
            <FileText className="h-4 w-4 text-indigo-400" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-foreground">{brief.headline}</div>
            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
              <span>{relativeTime(brief.created_at)}</span>
              <span>{ideas.length} idea{ideas.length === 1 ? "" : "s"}</span>
            </div>
          </div>
        </div>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {expanded ? "Hide ideas" : "Show ideas"}
        </button>
      </div>
      {expanded && ideas.length > 0 && (
        <div className="mt-3 pl-12 space-y-2.5">
          {ideas.map((idea, i) => (
            <div key={i} className="rounded-md border border-border bg-muted/20 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="text-sm font-medium text-foreground flex-1">{idea.title}</div>
                <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-medium shrink-0", confidenceStyles[idea.confidence])}>
                  {idea.confidence}
                </span>
              </div>
              {idea.hook && (
                <div className="text-xs text-muted-foreground mt-1.5">
                  <span className="text-foreground/70 font-medium">Hook: </span>
                  {idea.hook}
                </div>
              )}
              {idea.why_now && (
                <div className="text-xs text-muted-foreground mt-1">
                  <span className="text-foreground/70 font-medium">Why now: </span>
                  {idea.why_now}
                </div>
              )}
              {idea.citations?.length ? (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {idea.citations.map((c, j) => (
                    <span
                      key={j}
                      className="rounded-full border border-border bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground"
                    >
                      {c}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
