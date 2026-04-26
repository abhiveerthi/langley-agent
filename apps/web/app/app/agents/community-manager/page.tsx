"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  ArrowLeft,
  MessageCircle,
  Sparkles,
  AlertCircle,
  Loader2,
  RefreshCw,
  Filter,
  PenLine,
  Send,
  Search,
  Wrench,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MiniChat } from "@/components/chat/MiniChat";
import { YouTubeStatusPill } from "@/components/integrations/YouTubeStatusPill";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// /api/approvals returns whatever the approval_store has — Community Manager
// rows surface here as action_type=reply_comment.
type Approval = {
  id: string;
  org_id: string;
  thread_id: string | null;
  agent_slug: string | null;
  action_type: string;
  action_payload: Record<string, any>;
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

const capabilities: { title: string; body: string; icon: React.ElementType }[] = [
  {
    icon: Filter,
    title: "Triage recent comments",
    body: "Pulls the newest comments across all your videos and surfaces who's asking what — flagged questions, repeat themes, fans worth replying to.",
  },
  {
    icon: PenLine,
    title: "Draft a reply in your voice",
    body: "When you point it at a comment (\"reply to the one about pricing on the AI Tools video\"), it writes a draft using your brand voice and the latest Strategist brief.",
  },
  {
    icon: Send,
    title: "Post approved replies to YouTube",
    body: "Once you approve the draft, it posts the reply to YouTube via OAuth. Approval is required before any write fires — no auto-replies.",
  },
  {
    icon: Search,
    title: "Look up a channel",
    body: "Resolves a handle or channel id and pulls public stats. Useful when a commenter is themselves a creator worth context-checking.",
  },
];

const tools = [
  "get_recent_comments",
  "lookup_channel",
  "reply_to_comment",
];

export default function CommunityManagerAgentPage() {
  const [approvals, setApprovals] = useState<ApprovalsState>({ status: "loading" });

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
      const items = all.filter((a) => a.action_type === "reply_comment");
      setApprovals({ status: "ok", items });
    } catch (e) {
      setApprovals({ status: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    fetchApprovals();
  }, [fetchApprovals]);

  const pendingCount = approvals.status === "ok" ? approvals.items.length : 0;

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
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 border border-emerald-500/20">
              <MessageCircle className="h-5 w-5 text-emerald-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Community Manager</h1>
              <p className="text-sm text-muted-foreground">
                Triages YouTube comments, drafts replies in your voice, and posts approved replies via OAuth — gated by your approval.
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
          <Stat label="Pending replies" value={pendingCount.toString()} />
          <Stat label="Approval-gated writes" value="reply_to_comment" mono />
          <Stat label="Required" value="YouTube OAuth" />
        </div>

        {/* Capabilities */}
        <Section title="What the Community Manager does" subtitle="Drafting and triage are read-only. The only write — posting a reply — always requires your approval first.">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {capabilities.map((c) => (
              <CapabilityCard key={c.title} {...c} />
            ))}
          </div>
        </Section>

        {/* Approval flow */}
        <Section title="Approval flow" subtitle="Every reply runs through a single gate before it touches YouTube.">
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground mb-3">
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
              Reply to a comment
            </div>
            <ol className="space-y-2 text-sm text-muted-foreground">
              <li className="flex gap-2.5"><span className="text-emerald-400 font-mono">1.</span><span>You ask: <span className="text-foreground">&quot;reply to the comment about pricing on the AI Tools video&quot;</span></span></li>
              <li className="flex gap-2.5"><span className="text-emerald-400 font-mono">2.</span><span>It pulls recent comments, picks the target, drafts a reply in your voice.</span></li>
              <li className="flex gap-2.5"><span className="text-emerald-400 font-mono">3.</span><span>Pauses at the approval gate — you see the draft in chat (or in Slack if connected).</span></li>
              <li className="flex gap-2.5"><span className="text-emerald-400 font-mono">4.</span><span>You approve → reply posts to YouTube. You reject with feedback → it revises and re-pauses.</span></li>
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
                <Wrench className="h-3 w-3 text-emerald-400" />
                {t}
              </span>
            ))}
          </div>
        </Section>

        {/* Pending approvals */}
        <Section title="Pending replies" subtitle="Drafts waiting for your approval. Decide them in chat or on the Approvals page.">
          <ApprovalsList state={approvals} onRefresh={fetchApprovals} />
        </Section>
      </div>

      <div className="w-80 shrink-0 border-l border-border bg-card/50 overflow-y-auto p-5 space-y-6">
        <YouTubeStatusPill heading="Channel Connected" />

        <div className="rounded-lg border border-border bg-muted/20 p-4 text-xs text-muted-foreground space-y-2">
          <div className="flex items-center gap-2 text-foreground font-medium">
            <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
            How to use it
          </div>
          <p>
            Try <span className="text-foreground font-medium">&quot;triage my latest comments&quot;</span> or{" "}
            <span className="text-foreground font-medium">&quot;reply to the question about my mic on the studio tour&quot;</span>.
          </p>
          <p>
            YouTube must be connected with the <code className="font-mono text-foreground">force-ssl</code> scope so the agent can post replies. Check your{" "}
            <Link href="/app/integrations" className="text-emerald-400 hover:underline">Integrations</Link> page if posts are being rejected.
          </p>
        </div>
      </div>

      <MiniChat agentSlug="community-manager" agentName="Community Manager" />
    </div>
  );
}

// ── Subcomponents ─────────────────────────────────────────────────────────

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className={cn("text-2xl font-bold text-foreground", mono && "text-base font-mono mt-0.5")}>{value}</div>
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
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-emerald-500/10 border border-emerald-500/20">
        <Icon className="h-4 w-4 text-emerald-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="text-xs text-muted-foreground mt-1 leading-relaxed">{body}</div>
      </div>
    </div>
  );
}

function ApprovalsList({ state, onRefresh }: { state: ApprovalsState; onRefresh: () => void }) {
  if (state.status === "loading") {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
        <Loader2 className="h-6 w-6 text-muted-foreground animate-spin mx-auto mb-2" />
        <div className="text-sm text-muted-foreground">Loading…</div>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-5">
        <div className="flex items-center gap-2 mb-2">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-sm font-medium text-red-400">Couldn&apos;t load pending replies</span>
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
        <div className="text-sm text-foreground font-medium">No pending replies</div>
        <div className="text-xs text-muted-foreground mt-1">
          Drafted replies waiting for your decision will show up here.
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2.5">
      {state.items.map((a) => {
        const p = a.action_payload || {};
        return (
          <Link
            href={`/app/approvals`}
            key={a.id}
            className="block rounded-lg border border-border bg-card p-4 hover:border-emerald-500/40 transition-colors"
          >
            <div className="flex items-start justify-between gap-4 mb-1">
              <div className="text-sm font-medium text-foreground line-clamp-1">
                Reply to {p.parent_author || "commenter"} on {p.parent_video_title || "video"}
              </div>
              <span className="rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2.5 py-0.5 text-[11px] font-medium">
                Pending
              </span>
            </div>
            {p.parent_comment_text && (
              <div className="text-xs text-muted-foreground line-clamp-2 mb-2">
                <span className="text-foreground/70 font-medium">Their comment: </span>
                {p.parent_comment_text}
              </div>
            )}
            {p.reply_draft && (
              <div className="text-xs text-muted-foreground line-clamp-3 rounded-md bg-muted/30 border border-border p-2.5 mb-2">
                <span className="text-foreground/70 font-medium">Draft: </span>
                {p.reply_draft}
              </div>
            )}
            <div className="text-[11px] text-muted-foreground">{relativeTime(a.created_at)}</div>
          </Link>
        );
      })}
    </div>
  );
}
