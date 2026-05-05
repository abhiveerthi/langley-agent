"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  ArrowRight,
  Compass,
  Megaphone,
  MessageCircle,
  Briefcase,
  Scissors,
  Loader2,
  AlertCircle,
  RefreshCw,
  CheckSquare,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Mirrors packages/agents/registry.py. Editor lives here too even though it
// has no dashboard yet — surfacing the "coming soon" state is the entire
// point of this page.
type AgentMeta = {
  slug: string;
  name: string;
  tagline: string;
  href: string | null; // null = no dedicated dashboard yet
  icon: React.ElementType;
  accent: { bg: string; icon: string; border: string };
  status: "active" | "coming-soon";
  highlights: string[];
};

const AGENTS: AgentMeta[] = [
  {
    slug: "strategist",
    name: "Strategist",
    tagline: "Decides what to make next — channel analytics, niche trends, ranked video ideas.",
    href: "/app/agents/strategist",
    icon: Compass,
    accent: {
      bg: "bg-indigo-500/10",
      icon: "text-indigo-400",
      border: "border-indigo-500/20",
    },
    status: "active",
    highlights: ["Weekly briefs", "Hooks & outlines", "Competitor scan"],
  },
  {
    slug: "publisher",
    name: "Publisher",
    tagline: "Ships every video end-to-end — metadata, chapters, social drafts, approval-gated YouTube push.",
    href: "/app/agents/publisher",
    icon: Megaphone,
    accent: {
      bg: "bg-sky-500/10",
      icon: "text-sky-400",
      border: "border-sky-500/20",
    },
    status: "active",
    highlights: ["Metadata kits", "Tweet + newsletter", "Push to YouTube"],
  },
  {
    slug: "community-manager",
    name: "Community Manager",
    tagline: "Triages YouTube comments, drafts replies in your voice, posts approved replies.",
    href: "/app/agents/community-manager",
    icon: MessageCircle,
    accent: {
      bg: "bg-emerald-500/10",
      icon: "text-emerald-400",
      border: "border-emerald-500/20",
    },
    status: "active",
    highlights: ["Comment triage", "Voice-matched drafts", "Gated replies"],
  },
  {
    slug: "brand-manager",
    name: "Brand Manager",
    tagline: "Drafts sponsor outreach + tailored pitches, sends approved emails via Resend.",
    href: "/app/agents/brand-manager",
    icon: Briefcase,
    accent: {
      bg: "bg-amber-500/10",
      icon: "text-amber-400",
      border: "border-amber-500/20",
    },
    status: "active",
    highlights: ["Lead discovery", "Brand research", "Pitch sending"],
  },
  {
    slug: "editor",
    name: "Editor",
    tagline: "Cuts long-form video into shorts, dubs, captions, and thumbnails. Video worker not yet available.",
    href: "/app/agents/editor",
    icon: Scissors,
    accent: {
      bg: "bg-zinc-500/10",
      icon: "text-zinc-400",
      border: "border-zinc-500/20",
    },
    status: "coming-soon",
    highlights: ["Clips", "Dubbing", "Subtitles", "Thumbnails"],
  },
];

type Run = {
  id: string;
  agent_id: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
  agents?: { name: string; slug: string; icon?: string } | null;
};

type RunsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; items: Run[] };

type Approval = {
  id: string;
  agent_slug: string | null;
  action_type: string;
  preview: string | null;
  created_at: string;
  status: string;
};

type ApprovalsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; items: Approval[] };

// Single combined response from `GET /api/dashboard/overview`. The split
// into RunsState / ApprovalsState is preserved below so the existing
// `RecentRuns` / `PendingApprovals` subcomponents don't need rewrites.
type OverviewResponse = {
  runs: Run[];
  pending_approvals: Approval[];
};

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
  return new Date(iso).toLocaleDateString();
}

export default function AgentsPage() {
  const [runs, setRuns] = useState<RunsState>({ status: "loading" });
  const [approvals, setApprovals] = useState<ApprovalsState>({ status: "loading" });

  // Single round trip — see `GET /api/dashboard/overview`. Both halves
  // load and fail together, so a single network failure surfaces in
  // both subcomponents (their existing error-state UI handles it).
  const fetchOverview = useCallback(async () => {
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        const msg = "Not signed in";
        setRuns({ status: "error", message: msg });
        setApprovals({ status: "error", message: msg });
        return;
      }
      const res = await fetch(`${API}/api/dashboard/overview`, { headers: auth });
      if (!res.ok) {
        const msg = `HTTP ${res.status}`;
        setRuns({ status: "error", message: msg });
        setApprovals({ status: "error", message: msg });
        return;
      }
      const body = (await res.json()) as OverviewResponse;
      setRuns({ status: "ok", items: body.runs });
      setApprovals({ status: "ok", items: body.pending_approvals });
    } catch (e) {
      const msg = (e as Error).message;
      setRuns({ status: "error", message: msg });
      setApprovals({ status: "error", message: msg });
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void fetchOverview();
    });
  }, [fetchOverview]);

  return (
    <div className="p-6 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Agents</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Your back-office team. Each agent has a focused job and tools to do it.
          </p>
        </div>
      </div>

      {/* Pending approvals */}
      <PendingApprovals state={approvals} />

      {/* Roster */}
      <div className="grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
        {AGENTS.map((agent) => (
          <AgentCard key={agent.slug} agent={agent} />
        ))}
      </div>

      {/* Recent activity */}
      <RecentRuns state={runs} onRefresh={fetchOverview} />
    </div>
  );
}

function AgentCard({ agent }: { agent: AgentMeta }) {
  const Icon = agent.icon;
  const isActive = agent.status === "active";

  const inner = (
    <div
      className={cn(
        "rounded-lg border bg-card p-5 flex flex-col gap-4 h-full transition-shadow",
        agent.accent.border,
        isActive && "hover:shadow-md"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", agent.accent.bg)}>
            <Icon className={cn("h-5 w-5", agent.accent.icon)} />
          </div>
          <div className="min-w-0">
            <h2 className="font-semibold text-foreground leading-tight">{agent.name}</h2>
            <code className="text-[11px] font-mono text-muted-foreground">{agent.slug}</code>
          </div>
        </div>
        {isActive ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-400 shrink-0">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Active
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-500/10 px-2.5 py-1 text-xs font-medium text-zinc-400 shrink-0">
            Coming soon
          </span>
        )}
      </div>

      <p className="text-xs text-muted-foreground leading-relaxed">{agent.tagline}</p>

      <div className="flex flex-wrap gap-1.5">
        {agent.highlights.map((h) => (
          <span
            key={h}
            className="rounded-full border border-border bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground"
          >
            {h}
          </span>
        ))}
      </div>

      <div className="border-t border-border pt-3 mt-auto">
        {agent.href ? (
          <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", agent.accent.icon)}>
            {isActive ? "Open dashboard" : "Preview"}
            <ArrowRight className="h-3 w-3" />
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">No dashboard yet</span>
        )}
      </div>
    </div>
  );

  if (agent.href) {
    return (
      <Link href={agent.href} className="block">
        {inner}
      </Link>
    );
  }
  return <div className="opacity-70 cursor-not-allowed">{inner}</div>;
}

function PendingApprovals({ state }: { state: ApprovalsState }) {
  if (state.status !== "ok" || state.items.length === 0) return null;
  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 flex items-center gap-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 border border-amber-500/20">
        <CheckSquare className="h-4 w-4 text-amber-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-foreground">
          {state.items.length} pending approval{state.items.length === 1 ? "" : "s"}
        </div>
        <div className="text-xs text-muted-foreground mt-0.5">
          Drafts your agents are holding for your sign-off.
        </div>
      </div>
      <Link
        href="/app/approvals"
        className="flex items-center gap-1.5 rounded-md bg-amber-500/10 border border-amber-500/20 px-3 py-1.5 text-xs font-medium text-amber-400 hover:bg-amber-500/20 transition-colors shrink-0"
      >
        Review
        <ArrowRight className="h-3 w-3" />
      </Link>
    </div>
  );
}

function RecentRuns({ state, onRefresh }: { state: RunsState; onRefresh: () => void }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold text-foreground">Recent activity</h2>
        <button
          onClick={onRefresh}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <RefreshCw className="h-3 w-3" />
          Refresh
        </button>
      </div>
      <RecentRunsBody state={state} />
    </div>
  );
}

function RecentRunsBody({ state }: { state: RunsState }) {
  if (state.status === "loading") {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-6 text-center">
        <Loader2 className="h-5 w-5 text-muted-foreground animate-spin mx-auto mb-2" />
        <div className="text-sm text-muted-foreground">Loading runs…</div>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4">
        <div className="flex items-center gap-2 mb-1">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-sm font-medium text-red-400">Couldn&apos;t load runs</span>
        </div>
        <div className="text-xs text-muted-foreground">{state.message}</div>
      </div>
    );
  }
  if (state.items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
        <Sparkles className="h-5 w-5 text-muted-foreground mx-auto mb-2" />
        <div className="text-sm text-foreground font-medium">No agent runs yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Open any agent above and ask for something — it&apos;ll show up here.
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border bg-card divide-y divide-border">
      {state.items.map((r) => (
        <div key={r.id} className="flex items-center gap-4 px-5 py-3.5">
          <span
            className={cn(
              "h-2.5 w-2.5 shrink-0 rounded-full",
              r.status === "running"
                ? "bg-primary animate-pulse"
                : r.status === "complete"
                ? "bg-emerald-500"
                : r.status === "failed"
                ? "bg-red-500"
                : "bg-zinc-500"
            )}
          />
          <span className="flex-1 text-sm text-foreground/90 truncate">
            <span className="text-foreground font-medium">{r.agents?.name || "Agent"}</span>
            <span className="text-muted-foreground"> · {r.status}</span>
          </span>
          <span className="text-xs text-muted-foreground whitespace-nowrap">{relativeTime(r.started_at)}</span>
        </div>
      ))}
    </div>
  );
}
