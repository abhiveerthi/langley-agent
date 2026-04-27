"use client";

import Link from "next/link";
import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import {
  ArrowLeft,
  Megaphone,
  Video,
  AlertCircle,
  ExternalLink,
  Loader2,
  Globe,
  Eye,
  Lock,
  RefreshCw,
  Hash,
  ListOrdered,
  Type,
  Sparkles,
  Check,
  Wrench,
  ShieldCheck,
  FileText,
  Send,
  Search,
  PackageOpen,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MiniChat } from "@/components/chat/MiniChat";
import { YouTubeStatusPill } from "@/components/integrations/YouTubeStatusPill";
import { TwitterStatusPill } from "@/components/integrations/TwitterStatusPill";
import type { PublisherPackage, PublisherPackageStatus } from "@/lib/types/publisher";

type Tab = "uploads" | "packages";

type Upload = {
  video_id: string;
  title: string;
  description_preview: string;
  thumbnail: string | null;
  published_at: string;
  privacy_status: "public" | "unlisted" | "private" | "unknown" | null;
  duration: string | null;
};

type UploadsState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "disconnected" }
  | { status: "error"; message: string }
  | { status: "ok"; items: Upload[] };

type PackagesState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; items: PublisherPackage[] };

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

function parseIsoDuration(iso: string | null): string {
  if (!iso) return "";
  const m = iso.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (!m) return "";
  const h = parseInt(m[1] || "0", 10);
  const mins = parseInt(m[2] || "0", 10);
  const secs = parseInt(m[3] || "0", 10);
  const mm = String(mins).padStart(h ? 2 : 1, "0");
  const ss = String(secs).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
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

const packageStatusStyles: Record<PublisherPackage["status"], string> = {
  generating:   "bg-sky-500/10 text-sky-400 border-sky-500/20",
  draft:        "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
  pending_push: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  pushed:       "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
};

const packageStatusLabel: Record<PublisherPackage["status"], string> = {
  generating:   "Generating",
  draft:        "Draft",
  pending_push: "Pending Push",
  pushed:       "Pushed to YouTube",
};

const capabilities: { title: string; body: string; icon: React.ElementType }[] = [
  {
    icon: PackageOpen,
    title: "Package a video end-to-end",
    body: "Pulls the transcript + comments, then writes a full kit: title variants, description, tags, chapters, pinned comment, thumbnail copy ideas.",
  },
  {
    icon: FileText,
    title: "Repurpose for every platform",
    body: "Drafts 3 tweets, an X thread outline, a LinkedIn post, an Instagram caption, and a newsletter blurb — all grounded in the transcript.",
  },
  {
    icon: Send,
    title: "Push metadata + tweets on approval",
    body: "Writes new title/description/tags to YouTube via the API, or posts a tweet to X. Both writes pause for your sign-off first.",
  },
  {
    icon: Search,
    title: "Re-read before re-creating",
    body: "Knows what's already packaged. If you mention a video by title (\"the lasagna one\"), it surfaces the existing kit instead of regenerating.",
  },
];

const tools = [
  "get_latest_upload",
  "get_video_details",
  "get_video_transcript",
  "get_video_comments",
  "suggest_seo_keywords",
  "list_packages",
  "get_package",
  "get_package_by_video",
  "update_video_metadata",
  "post_tweet",
];

const privacyStyles: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  public:   { icon: Globe, color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20", label: "Public" },
  unlisted: { icon: Eye,   color: "text-sky-400 bg-sky-500/10 border-sky-500/20", label: "Unlisted" },
  private:  { icon: Lock,  color: "text-zinc-400 bg-zinc-500/10 border-zinc-500/20", label: "Private" },
  unknown:  { icon: Eye,   color: "text-muted-foreground bg-muted/30 border-border", label: "Unknown" },
};

export default function PublisherAgentPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState<Tab>("uploads");
  const [uploads, setUploads] = useState<UploadsState>({ status: "idle" });
  const [packages, setPackages] = useState<PackagesState>({ status: "loading" });
  const [toast, setToast] = useState<string | null>(null);
  const [packagingId, setPackagingId] = useState<string | null>(null);

  // ── Fetchers ──────────────────────────────────────────────────────────
  const fetchUploads = useCallback(async () => {
    setUploads({ status: "loading" });
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setUploads({ status: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/integrations/youtube/uploads?limit=12`, { headers: auth });
      if (res.status === 400) {
        setUploads({ status: "disconnected" });
        return;
      }
      if (!res.ok) {
        setUploads({ status: "error", message: `HTTP ${res.status}` });
        return;
      }
      const items = (await res.json()) as Upload[];
      setUploads({ status: "ok", items });
    } catch (e) {
      setUploads({ status: "error", message: (e as Error).message });
    }
  }, []);

  const fetchPackages = useCallback(async () => {
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/publisher/packages`, { headers: auth });
      if (!res.ok) {
        setPackages({ status: "error", message: `HTTP ${res.status}` });
        return;
      }
      const items = (await res.json()) as PublisherPackage[];
      setPackages({ status: "ok", items });
    } catch (e) {
      setPackages({ status: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    fetchUploads();
    fetchPackages();
  }, [fetchUploads, fetchPackages]);

  // Handle ?youtube=connected|error redirect params once
  useEffect(() => {
    const yt = searchParams.get("youtube");
    if (!yt) return;
    if (yt === "connected") setToast("YouTube connected");
    else if (yt === "error") {
      const reason = searchParams.get("reason") || "unknown";
      setToast(`YouTube connect failed: ${reason.slice(0, 80)}`);
    }
    const url = new URL(window.location.href);
    url.searchParams.delete("youtube");
    url.searchParams.delete("reason");
    router.replace(url.pathname + (url.search ? url.search : ""));
  }, [searchParams, router]);

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2200);
    return () => clearTimeout(t);
  }, [toast]);

  // ── Actions ───────────────────────────────────────────────────────────
  async function packageFromUpload(u: Upload) {
    if (packagingId) return;
    setPackagingId(u.video_id);
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/publisher/packages`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ video_id: u.video_id, video_title: u.title }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { package_id: string };
      router.push(`/app/agents/publisher/packages/${data.package_id}`);
    } catch (e) {
      setToast(`Package failed: ${(e as Error).message}`);
      setPackagingId(null);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────
  const packagesCount = packages.status === "ok" ? packages.items.length : 0;
  const pendingCount = packages.status === "ok"
    ? packages.items.filter((p) => p.status === "pending_push" || p.status === "generating").length
    : 0;

  // Fast lookup: has this video_id already been packaged?
  const packagesByVideoId = useMemo(() => {
    const map = new Map<string, { id: string; status: PublisherPackageStatus }>();
    if (packages.status === "ok") {
      for (const p of packages.items) map.set(p.video_id, { id: p.id, status: p.status });
    }
    return map;
  }, [packages]);

  return (
    <div className="flex h-full min-h-0 relative">
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
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-sky-500/10 border border-sky-500/20">
              <Megaphone className="h-5 w-5 text-sky-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Publisher</h1>
              <p className="text-sm text-muted-foreground">Ships every video end-to-end — metadata, chapters, and social drafts</p>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-sm font-medium text-emerald-400">Active</span>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "Uploads", value: uploads.status === "ok" ? uploads.items.length.toString() : "—" },
            { label: "Packages", value: packagesCount.toString() },
            { label: "In Progress", value: pendingCount.toString() },
          ].map((stat) => (
            <div key={stat.label} className="rounded-lg border border-border bg-card p-4">
              <div className="text-2xl font-bold text-foreground">{stat.value}</div>
              <div className="text-xs text-muted-foreground mt-1">{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Capabilities */}
        <Section title="What the Publisher does" subtitle="Read tools run free. Both writes — YouTube metadata and tweets — pause for your approval first.">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {capabilities.map((c) => (
              <CapabilityCard key={c.title} {...c} />
            ))}
          </div>
        </Section>

        {/* Approval flow */}
        <Section title="Approval flow" subtitle="Two independent gates — you can push metadata without sending the tweet, or vice versa.">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="rounded-lg border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground mb-3">
                <ShieldCheck className="h-4 w-4 text-sky-400" />
                Push to YouTube
              </div>
              <ol className="space-y-2 text-sm text-muted-foreground">
                <li className="flex gap-2.5"><span className="text-sky-400 font-mono">1.</span><span>Open a draft package and pick a title variant.</span></li>
                <li className="flex gap-2.5"><span className="text-sky-400 font-mono">2.</span><span>Hit Push — agent shows the exact title / description / tags it&apos;ll write.</span></li>
                <li className="flex gap-2.5"><span className="text-sky-400 font-mono">3.</span><span>Approve → <code className="font-mono text-foreground">videos.update</code> writes to your channel.</span></li>
              </ol>
            </div>
            <div className="rounded-lg border border-border bg-card p-5">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground mb-3">
                <ShieldCheck className="h-4 w-4 text-sky-400" />
                Post to X
              </div>
              <ol className="space-y-2 text-sm text-muted-foreground">
                <li className="flex gap-2.5"><span className="text-sky-400 font-mono">1.</span><span>From a package, hit Post on the social.twitter copy.</span></li>
                <li className="flex gap-2.5"><span className="text-sky-400 font-mono">2.</span><span>Agent shows the exact tweet text it&apos;ll send.</span></li>
                <li className="flex gap-2.5"><span className="text-sky-400 font-mono">3.</span><span>Approve → <code className="font-mono text-foreground">post_tweet</code> publishes to your X account.</span></li>
              </ol>
            </div>
          </div>
        </Section>

        {/* Tools */}
        <Section title="Tools available" subtitle="The functions the agent can call. The last two are the only writes.">
          <div className="flex flex-wrap gap-1.5">
            {tools.map((t) => {
              const isWrite = t === "update_video_metadata" || t === "post_tweet";
              return (
                <span
                  key={t}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-mono",
                    isWrite
                      ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                      : "border-border bg-muted/30 text-muted-foreground",
                  )}
                >
                  <Wrench className={cn("h-3 w-3", isWrite ? "text-amber-400" : "text-sky-400")} />
                  {t}
                </span>
              );
            })}
          </div>
        </Section>

        {/* Uploads / packages tabs */}
        <Section title="Your videos & packages" subtitle="Click Package this on any upload to draft a kit. Existing packages link straight to their detail page.">
          <div className="flex border-b border-border mb-4">
            {(["uploads", "packages"] as Tab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={cn(
                  "px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px flex items-center gap-2",
                  activeTab === tab
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {tab === "uploads" ? "Recent Uploads" : "Packages"}
                {tab === "uploads" && uploads.status === "ok" && (
                  <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-sky-500/20 px-1 text-[10px] font-semibold text-sky-400">
                    {uploads.items.length}
                  </span>
                )}
                {tab === "packages" && packagesCount > 0 && (
                  <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-muted/40 px-1 text-[10px] font-semibold text-muted-foreground">
                    {packagesCount}
                  </span>
                )}
              </button>
            ))}
          </div>

          {activeTab === "uploads" && (
            <UploadsTab
              state={uploads}
              onRefresh={fetchUploads}
              onPackage={packageFromUpload}
              packagingId={packagingId}
              packagesByVideoId={packagesByVideoId}
            />
          )}

          {activeTab === "packages" && (
            <PackagesTab state={packages} onRefresh={fetchPackages} />
          )}
        </Section>
      </div>

      {/* Right sidebar */}
      <div className="w-80 shrink-0 border-l border-border bg-card/50 overflow-y-auto p-5 space-y-6">
        <YouTubeStatusPill heading="Channel Connected" />

        <TwitterStatusPill heading="X / Twitter" />

        <div className="rounded-lg border border-border bg-muted/20 p-4 text-xs text-muted-foreground space-y-2">
          <div className="flex items-center gap-2 text-foreground font-medium">
            <Sparkles className="h-3.5 w-3.5 text-sky-400" />
            How to use it
          </div>
          <p>
            Click <span className="text-foreground font-medium">Package this</span> on any upload, or ask in chat:{" "}
            <span className="text-foreground font-medium">&quot;package my latest&quot;</span>.
          </p>
          <p>
            X must be connected for tweet pushes. YouTube metadata pushes only need your YouTube connection.
          </p>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-lg border border-border bg-card/95 backdrop-blur px-4 py-2.5 shadow-lg flex items-center gap-2">
          <Check className="h-4 w-4 text-emerald-400" />
          <span className="text-sm text-foreground">{toast}</span>
        </div>
      )}

      <MiniChat agentSlug="publisher" agentName="Publisher" />
    </div>
  );
}

// ── Shared layout helpers ────────────────────────────────────────────────

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
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-sky-500/10 border border-sky-500/20">
        <Icon className="h-4 w-4 text-sky-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <div className="text-xs text-muted-foreground mt-1 leading-relaxed">{body}</div>
      </div>
    </div>
  );
}

// ── Uploads tab ──────────────────────────────────────────────────────────

function UploadsTab({
  state,
  onRefresh,
  onPackage,
  packagingId,
  packagesByVideoId,
}: {
  state: UploadsState;
  onRefresh: () => void;
  onPackage: (u: Upload) => void;
  packagingId: string | null;
  packagesByVideoId: Map<string, { id: string; status: PublisherPackageStatus }>;
}) {
  if (state.status === "idle" || state.status === "loading") {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
        <Loader2 className="h-6 w-6 text-muted-foreground animate-spin mx-auto mb-2" />
        <div className="text-sm text-muted-foreground">Loading your uploads…</div>
      </div>
    );
  }
  if (state.status === "disconnected") {
    return (
      <Link
        href="/app/integrations"
        className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border bg-muted/10 p-8 hover:border-sky-500/40 hover:bg-sky-500/5 transition-colors text-center"
      >
        <Video className="h-6 w-6 text-muted-foreground" />
        <div className="text-sm font-medium text-foreground">YouTube is not connected</div>
        <div className="text-xs text-sky-400">Connect in Integrations →</div>
      </Link>
    );
  }
  if (state.status === "error") {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-5">
        <div className="flex items-center gap-2 mb-2">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-sm font-medium text-red-400">Couldn&apos;t load uploads</span>
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
  if (state.status === "ok" && state.items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
        <div className="text-sm text-muted-foreground">No videos on this channel yet.</div>
      </div>
    );
  }
  return (
    <>
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-muted-foreground">
          {state.items.length} most recent · including unlisted
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <RefreshCw className="h-3 w-3" />
          Refresh
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {state.items.map((u) => (
          <UploadCard
            key={u.video_id}
            upload={u}
            onPackage={() => onPackage(u)}
            isPackaging={packagingId === u.video_id}
            existingPackage={packagesByVideoId.get(u.video_id) ?? null}
          />
        ))}
      </div>
    </>
  );
}

function UploadCard({
  upload,
  onPackage,
  isPackaging,
  existingPackage,
}: {
  upload: Upload;
  onPackage: () => void;
  isPackaging: boolean;
  existingPackage: { id: string; status: PublisherPackageStatus } | null;
}) {
  const privacy = privacyStyles[upload.privacy_status || "unknown"] || privacyStyles.unknown;
  const PrivacyIcon = privacy.icon;
  const duration = parseIsoDuration(upload.duration);
  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden flex flex-col">
      <div className="relative aspect-video bg-muted">
        {upload.thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={upload.thumbnail} alt="" className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Video className="h-8 w-8 text-muted-foreground" />
          </div>
        )}
        {duration && (
          <span className="absolute bottom-2 right-2 rounded bg-black/80 px-1.5 py-0.5 text-[11px] font-medium text-white">
            {duration}
          </span>
        )}
        <span
          className={cn(
            "absolute top-2 left-2 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium backdrop-blur-sm",
            privacy.color,
          )}
        >
          <PrivacyIcon className="h-3 w-3" />
          {privacy.label}
        </span>
      </div>
      <div className="p-3 flex-1 flex flex-col gap-2">
        <div className="text-sm font-medium text-foreground line-clamp-2">{upload.title}</div>
        <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <span>{relativeTime(upload.published_at)}</span>
          <span className="font-mono truncate">{upload.video_id}</span>
        </div>
        <div className="flex items-center gap-2 mt-auto pt-2">
          {existingPackage ? (
            <Link
              href={`/app/agents/publisher/packages/${existingPackage.id}`}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-md bg-muted/40 border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted/60 transition-colors"
            >
              {existingPackage.status === "generating" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : existingPackage.status === "pushed" ? (
                <Check className="h-3.5 w-3.5 text-emerald-400" />
              ) : (
                <Sparkles className="h-3.5 w-3.5" />
              )}
              {existingPackage.status === "generating"
                ? "Generating…"
                : existingPackage.status === "pushed"
                ? "View (pushed)"
                : "View Package"}
            </Link>
          ) : (
            <button
              onClick={onPackage}
              disabled={isPackaging}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-md bg-sky-500/10 border border-sky-500/20 px-3 py-1.5 text-xs font-medium text-sky-400 hover:bg-sky-500/20 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isPackaging ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
              {isPackaging ? "Starting…" : "Package this"}
            </button>
          )}
          <a
            href={`https://studio.youtube.com/video/${upload.video_id}/edit`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-1 rounded-md border border-border px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </div>
    </div>
  );
}

// ── Packages tab ─────────────────────────────────────────────────────────

function PackagesTab({
  state,
  onRefresh,
}: {
  state: PackagesState;
  onRefresh: () => void;
}) {
  if (state.status === "loading") {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
        <Loader2 className="h-6 w-6 text-muted-foreground animate-spin mx-auto mb-2" />
        <div className="text-sm text-muted-foreground">Loading packages…</div>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-5">
        <div className="flex items-center gap-2 mb-2">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-sm font-medium text-red-400">Couldn&apos;t load packages</span>
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
        <div className="text-sm text-foreground font-medium">No packages yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Click <span className="text-foreground">Package this</span> on any upload to generate your first kit.
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {state.items.map((pkg) => (
        <PackageRow key={pkg.id} pkg={pkg} />
      ))}
    </div>
  );
}

function PackageRow({ pkg }: { pkg: PublisherPackage }) {
  return (
    <Link
      href={`/app/agents/publisher/packages/${pkg.id}`}
      className="block rounded-lg border border-border bg-card p-4 hover:border-sky-500/40 transition-colors"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <div className="flex h-12 w-20 shrink-0 items-center justify-center rounded-md bg-linear-to-br from-sky-500/20 to-indigo-500/20 border border-border">
            <Video className="h-4 w-4 text-sky-400" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-foreground truncate">{pkg.video_title}</div>
            <div className="text-xs text-muted-foreground mt-0.5 font-mono">{pkg.video_id}</div>
            <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><Type className="h-3 w-3" /> {pkg.title_variants.length} titles</span>
              <span className="flex items-center gap-1"><Hash className="h-3 w-3" /> {pkg.tags.length} tags</span>
              <span className="flex items-center gap-1"><ListOrdered className="h-3 w-3" /> {pkg.chapters.length} chapters</span>
            </div>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2 shrink-0">
          <span className={cn("rounded-full border px-2.5 py-0.5 text-[11px] font-medium", packageStatusStyles[pkg.status])}>
            {packageStatusLabel[pkg.status]}
          </span>
          <div className="text-[11px] text-muted-foreground">{relativeTime(pkg.updated_at)}</div>
        </div>
      </div>
    </Link>
  );
}
