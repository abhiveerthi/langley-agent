"use client";

import Link from "next/link";
import { useState, useMemo, useEffect } from "react";
import {
  ArrowLeft,
  Megaphone,
  CheckCircle2,
  Video,
  FileText,
  Copy,
  Upload,
  AlertCircle,
  ExternalLink,
  Hash,
  ListOrdered,
  Type,
  Sparkles,
  Clock,
  X,
  Check,
  MessageSquare,
  Image as ImageIcon,
  Send,
  Briefcase,
  Camera,
  Mail,
  Pencil,
} from "lucide-react";
import {
  publishedPackages as seedPackages,
  pendingApprovals as seedApprovals,
  type PublisherPackage,
  type PendingApproval,
} from "@/lib/mock-data";
import { cn } from "@/lib/utils";
import { MiniChat } from "@/components/chat/MiniChat";

type Tab = "packages" | "social" | "approvals";

const statusStyles: Record<string, string> = {
  draft:   "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
  pending: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  pushed:  "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
};

const statusLabel: Record<string, string> = {
  draft:   "Draft",
  pending: "Pending Approval",
  pushed:  "Pushed to YouTube",
};

const defaultPlatforms = [
  { label: "X (Twitter)", enabled: true },
  { label: "X Thread", enabled: true },
  { label: "LinkedIn", enabled: true },
  { label: "Instagram Caption", enabled: true },
  { label: "Newsletter blurb", enabled: true },
];

const preferences = [
  { label: "Auto-package new uploads", enabled: true, desc: "Run Publisher when a new unlisted video appears" },
  { label: "Require approval before push", enabled: true, desc: "Never write to YouTube without your OK" },
  { label: "Include thumbnail text ideas", enabled: true, desc: "Overlay copy only — no image generation" },
];

function formatPackageAsText(pkg: PublisherPackage) {
  const lines: string[] = [];
  lines.push(`# ${pkg.videoTitle}\n`);
  lines.push("## Title variants");
  pkg.titleVariants.forEach((t, i) => lines.push(`${i + 1}. ${t}`));
  lines.push("\n## Description");
  lines.push(pkg.description);
  lines.push("\n## Tags");
  lines.push(pkg.tags.join(", "));
  lines.push("\n## Chapters");
  pkg.chapters.forEach((c) => lines.push(`${c.time} — ${c.label}`));
  lines.push("\n## Pinned comment");
  lines.push(pkg.pinnedComment);
  lines.push("\n## Thumbnail ideas");
  pkg.thumbnailIdeas.forEach((t, i) => lines.push(`${i + 1}. ${t}`));
  lines.push("\n## Tweets");
  pkg.socialKit.tweets.forEach((t, i) => lines.push(`--- Tweet ${i + 1} ---\n${t}`));
  lines.push("\n## Thread outline");
  pkg.socialKit.threadOutline.forEach((t, i) => lines.push(`${i + 1}. ${t}`));
  lines.push("\n## LinkedIn");
  lines.push(pkg.socialKit.linkedin);
  lines.push("\n## Instagram");
  lines.push(pkg.socialKit.instagram);
  lines.push("\n## Newsletter");
  lines.push(pkg.socialKit.newsletter);
  return lines.join("\n");
}

export default function PublisherAgentPage() {
  const [activeTab, setActiveTab] = useState<Tab>("packages");
  const [packages, setPackages] = useState<PublisherPackage[]>(seedPackages);
  const [approvals, setApprovals] = useState<PendingApproval[]>(seedApprovals);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const approvalCount = approvals.length;
  const detailPkg = useMemo(() => packages.find((p) => p.id === detailId) ?? null, [packages, detailId]);

  const totalDrafts = useMemo(
    () =>
      packages.reduce(
        (n, p) =>
          n +
          p.socialKit.tweets.length +
          p.socialKit.threadOutline.length +
          1 /* linkedin */ +
          1 /* ig */ +
          1 /* newsletter */,
        0,
      ),
    [packages],
  );

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2200);
    return () => clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    if (!copiedKey) return;
    const t = setTimeout(() => setCopiedKey(null), 1500);
    return () => clearTimeout(t);
  }, [copiedKey]);

  async function copy(text: string, key: string, label?: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      if (label) setToast(`Copied ${label}`);
    } catch {
      setToast("Copy failed");
    }
  }

  function pushToYouTube(pkgId: string) {
    const pkg = packages.find((p) => p.id === pkgId);
    if (!pkg) return;
    setPackages((prev) => prev.map((p) => (p.id === pkgId ? { ...p, status: "pending" } : p)));
    setApprovals((prev) => [
      {
        id: `a-${pkgId}-${Date.now()}`,
        packageId: pkgId,
        videoId: pkg.videoId,
        videoTitle: pkg.videoTitle,
        proposedTitle: pkg.titleVariants[0],
        currentTitle: "final_v3.mp4",
        proposedTagCount: pkg.tags.length,
        proposedChapterCount: pkg.chapters.length,
        requestedAt: "just now",
      },
      ...prev,
    ]);
    setActiveTab("approvals");
    setToast("Approval requested");
  }

  function approve(approvalId: string) {
    const a = approvals.find((x) => x.id === approvalId);
    if (!a) return;
    setPackages((prev) => prev.map((p) => (p.id === a.packageId ? { ...p, status: "pushed" } : p)));
    setApprovals((prev) => prev.filter((x) => x.id !== approvalId));
    setToast("Pushed to YouTube");
  }

  function reject(approvalId: string) {
    const a = approvals.find((x) => x.id === approvalId);
    if (!a) return;
    setPackages((prev) => prev.map((p) => (p.id === a.packageId ? { ...p, status: "draft" } : p)));
    setApprovals((prev) => prev.filter((x) => x.id !== approvalId));
    setToast("Approval rejected — package kept as draft");
  }

  function packageLatest() {
    const id = `p-${Date.now()}`;
    const videoId = `new${Math.random().toString(36).slice(2, 10)}`;
    const stub: PublisherPackage = {
      id,
      videoId,
      videoTitle: "Your Newest Upload (auto-detected)",
      status: "pending",
      packagedAt: "just now",
      titleVariants: [
        "Your Newest Upload (auto-detected)",
        "Draft Title Variant #2",
        "Draft Title Variant #3",
      ],
      description: "Auto-generated description draft from the transcript. Edit before push.",
      tags: ["draft-tag-1", "draft-tag-2", "draft-tag-3"],
      chapters: [
        { time: "00:00", label: "Intro" },
        { time: "02:00", label: "Main point" },
        { time: "08:00", label: "Wrap" },
      ],
      pinnedComment: "What did you want more of in this one? Let me know for the follow-up.",
      thumbnailIdeas: [
        "Bold number + subtitle",
        "Face forward + single word overlay",
        "Before/after split composition",
      ],
      socialKit: {
        tweets: ["Draft tweet 1", "Draft tweet 2", "Draft tweet 3"],
        threadOutline: ["Hook", "Main 1", "Main 2", "Main 3", "CTA"],
        linkedin: "Draft LinkedIn post — edit before sending.",
        instagram: "Draft IG caption — edit before sending.",
        newsletter: "Draft newsletter blurb — edit before sending.",
      },
    };
    setPackages((prev) => [stub, ...prev]);
    setApprovals((prev) => [
      {
        id: `a-${id}-${Date.now()}`,
        packageId: id,
        videoId,
        videoTitle: stub.videoTitle,
        proposedTitle: stub.titleVariants[0],
        currentTitle: "final_v3.mp4",
        proposedTagCount: stub.tags.length,
        proposedChapterCount: stub.chapters.length,
        requestedAt: "just now",
      },
      ...prev,
    ]);
    setActiveTab("approvals");
    setToast("New package drafted — awaiting approval");
  }

  return (
    <div className="flex h-full min-h-0 relative">
      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <div>
          <Link
            href="/app/agents"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3 transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            All Agents
          </Link>
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-sky-500/10 border border-sky-500/20">
              <Megaphone className="h-5 w-5 text-sky-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Publisher</h1>
              <p className="text-sm text-muted-foreground">Ships every video, everywhere — titles, chapters, tags, and a week of social drafts</p>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-sm font-medium text-emerald-400">Active</span>
            </div>
          </div>
        </div>

        {/* Approval banner */}
        {approvalCount > 0 && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 flex items-start gap-4">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/10">
              <AlertCircle className="h-4 w-4 text-amber-400" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-foreground">
                {approvalCount} metadata push{approvalCount === 1 ? "" : "es"} awaiting your approval
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                Publisher has drafted YouTube metadata and is waiting before writing to your channel.
              </div>
            </div>
            <button
              onClick={() => setActiveTab("approvals")}
              className="shrink-0 rounded-md bg-amber-500/10 border border-amber-500/30 px-3 py-1.5 text-xs font-medium text-amber-400 hover:bg-amber-500/20 transition-colors"
            >
              Review
            </button>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "Videos Packaged", value: packages.length.toString() },
            { label: "Pending Approval", value: approvalCount.toString() },
            { label: "Social Drafts", value: totalDrafts.toString() },
          ].map((stat) => (
            <div key={stat.label} className="rounded-lg border border-border bg-card p-4">
              <div className="text-2xl font-bold text-foreground">{stat.value}</div>
              <div className="text-xs text-muted-foreground mt-1">{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div>
          <div className="flex border-b border-border mb-4">
            {(["packages", "social", "approvals"] as Tab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={cn(
                  "px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px flex items-center gap-2",
                  activeTab === tab
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {tab === "packages" ? "Packages" : tab === "social" ? "Social Kits" : "Approvals"}
                {tab === "approvals" && approvalCount > 0 && (
                  <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500/20 px-1 text-[10px] font-semibold text-amber-400">
                    {approvalCount}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Packages */}
          {activeTab === "packages" && (
            <div className="space-y-3">
              {packages.map((pkg) => (
                <div key={pkg.id} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-4">
                    <button
                      onClick={() => setDetailId(pkg.id)}
                      className="flex items-start gap-3 min-w-0 flex-1 text-left hover:opacity-90 transition-opacity"
                    >
                      <div className="flex h-12 w-20 shrink-0 items-center justify-center rounded-md bg-linear-to-br from-sky-500/20 to-indigo-500/20 border border-border">
                        <Video className="h-4 w-4 text-sky-400" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium text-foreground truncate">{pkg.videoTitle}</div>
                        <div className="text-xs text-muted-foreground mt-0.5 font-mono">{pkg.videoId}</div>
                        <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                          <span className="flex items-center gap-1"><Type className="h-3 w-3" /> {pkg.titleVariants.length} titles</span>
                          <span className="flex items-center gap-1"><Hash className="h-3 w-3" /> {pkg.tags.length} tags</span>
                          <span className="flex items-center gap-1"><ListOrdered className="h-3 w-3" /> {pkg.chapters.length} chapters</span>
                          <span className="flex items-center gap-1 text-sky-400"><Sparkles className="h-3 w-3" /> Social kit</span>
                        </div>
                      </div>
                    </button>
                    <div className="flex flex-col items-end gap-2 shrink-0">
                      <span className={cn("rounded-full border px-2.5 py-0.5 text-[11px] font-medium", statusStyles[pkg.status])}>
                        {statusLabel[pkg.status]}
                      </span>
                      <div className="text-[11px] text-muted-foreground">{pkg.packagedAt}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 mt-3 pl-23">
                    <button
                      onClick={() => setDetailId(pkg.id)}
                      className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                    >
                      <FileText className="h-3.5 w-3.5" />
                      View Kit
                    </button>
                    {pkg.status === "draft" && (
                      <button
                        onClick={() => pushToYouTube(pkg.id)}
                        className="flex items-center gap-1.5 rounded-md bg-sky-500/10 border border-sky-500/20 px-3 py-1.5 text-xs font-medium text-sky-400 hover:bg-sky-500/20 transition-colors"
                      >
                        <Upload className="h-3.5 w-3.5" />
                        Push to YouTube
                      </button>
                    )}
                    {pkg.status === "pushed" && (
                      <a
                        href={`https://studio.youtube.com/video/${pkg.videoId}/edit`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        Open in Studio
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Social Kits */}
          {activeTab === "social" && (
            <div className="space-y-3">
              {packages.map((pkg) => {
                const kit = pkg.socialKit;
                return (
                  <div key={pkg.id} className="rounded-lg border border-border bg-card p-4">
                    <div className="flex items-start justify-between gap-4">
                      <button
                        onClick={() => setDetailId(pkg.id)}
                        className="flex items-center gap-3 min-w-0 text-left hover:opacity-90 transition-opacity"
                      >
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-500/10">
                          <Sparkles className="h-4 w-4 text-sky-400" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-foreground truncate">{pkg.videoTitle}</div>
                          <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1.5">
                            <Clock className="h-3 w-3" />
                            {pkg.packagedAt}
                          </div>
                        </div>
                      </button>
                      <button
                        onClick={() =>
                          copy(formatPackageAsText(pkg), `all-${pkg.id}`, "full kit")
                        }
                        className="shrink-0 flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                      >
                        {copiedKey === `all-${pkg.id}` ? (
                          <Check className="h-3.5 w-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="h-3.5 w-3.5" />
                        )}
                        Copy All
                      </button>
                    </div>
                    <div className="mt-3 pl-12 flex flex-wrap gap-2">
                      <KitCountPill icon={Send} label="Tweets" count={kit.tweets.length} />
                      <KitCountPill icon={MessageSquare} label="Thread" count={kit.threadOutline.length} />
                      <KitCountPill icon={Briefcase} label="LinkedIn" count={1} />
                      <KitCountPill icon={Camera} label="Instagram" count={1} />
                      <KitCountPill icon={Mail} label="Newsletter" count={1} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Approvals */}
          {activeTab === "approvals" && (
            <div className="space-y-3">
              {approvals.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
                  <CheckCircle2 className="h-8 w-8 text-emerald-400 mx-auto mb-2" />
                  <div className="text-sm font-medium text-foreground">No pending approvals</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    New packages will appear here before anything is written to YouTube.
                  </div>
                </div>
              ) : (
                approvals.map((a) => (
                  <div key={a.id} className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-5">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <div className="text-sm font-semibold text-foreground">{a.videoTitle}</div>
                        <div className="text-xs text-muted-foreground mt-0.5 font-mono">{a.videoId} · requested {a.requestedAt}</div>
                      </div>
                      <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[11px] font-medium text-amber-400">
                        videos.update
                      </span>
                    </div>

                    <div className="space-y-2.5 mb-4">
                      <div className="rounded-md border border-border bg-background/50 p-3">
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">Current title</div>
                        <div className="text-sm font-mono text-muted-foreground line-through">{a.currentTitle}</div>
                      </div>
                      <div className="rounded-md border border-sky-500/30 bg-sky-500/5 p-3">
                        <div className="text-[10px] font-semibold uppercase tracking-wider text-sky-400 mb-1">Proposed title</div>
                        <div className="text-sm text-foreground">{a.proposedTitle}</div>
                        <div className="text-xs text-muted-foreground mt-1.5">
                          + new description, {a.proposedTagCount} tags, {a.proposedChapterCount} chapters
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => approve(a.id)}
                        className="flex-1 flex items-center justify-center gap-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/30 px-3 py-2 text-sm font-medium text-emerald-400 hover:bg-emerald-500/20 transition-colors"
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        Approve &amp; Push
                      </button>
                      <button
                        onClick={() => setDetailId(a.packageId)}
                        className="flex items-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                      >
                        <Pencil className="h-4 w-4" />
                        Edit
                      </button>
                      <button
                        onClick={() => reject(a.id)}
                        className="flex items-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm font-medium text-muted-foreground hover:text-red-400 hover:border-red-500/30 transition-colors"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </div>

      {/* Right config panel */}
      <div className="w-80 shrink-0 border-l border-border bg-card/50 overflow-y-auto p-5 space-y-6">
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">YouTube</h3>
          <div className="rounded-md border border-border bg-muted/20 px-3 py-3 flex items-center gap-3">
            <div className="h-9 w-9 shrink-0 rounded-full bg-linear-to-br from-red-500 to-orange-500 flex items-center justify-center text-white text-sm font-bold">
              YT
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-foreground truncate">Your Channel</div>
              <div className="text-xs text-muted-foreground mt-0.5">OAuth · force-ssl scope</div>
            </div>
            <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-foreground">Voice Reference</h3>
            <button className="text-xs text-primary hover:underline">Replace</button>
          </div>
          <div className="rounded-md border border-border bg-muted/20 px-3 py-3 flex items-center gap-3">
            <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-foreground truncate">voice-and-style.gdoc</div>
              <div className="text-xs text-muted-foreground mt-0.5">Informs every draft</div>
            </div>
            <ExternalLink className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          </div>
        </div>

        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Default Platforms</h3>
          <TogglesList items={defaultPlatforms} />
        </div>

        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Preferences</h3>
          <div className="space-y-2">
            {preferences.map((item, i) => (
              <PreferenceRow key={item.label} item={item} index={i} />
            ))}
          </div>
        </div>

        <button
          onClick={packageLatest}
          className="w-full flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors"
        >
          <Megaphone className="h-4 w-4" />
          Package Latest Upload
        </button>
      </div>

      {/* Detail drawer */}
      {detailPkg && (
        <PackageDetailDrawer
          pkg={detailPkg}
          onClose={() => setDetailId(null)}
          onCopy={copy}
          copiedKey={copiedKey}
          onApproveAndPush={() => {
            const a = approvals.find((x) => x.packageId === detailPkg.id);
            if (a) approve(a.id);
            else pushToYouTube(detailPkg.id);
            setDetailId(null);
          }}
        />
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-lg border border-border bg-card/95 backdrop-blur px-4 py-2.5 shadow-lg flex items-center gap-2">
          <Check className="h-4 w-4 text-emerald-400" />
          <span className="text-sm text-foreground">{toast}</span>
        </div>
      )}

      {/* Mini Chat */}
      <MiniChat agentSlug="publisher" agentName="Publisher" />
    </div>
  );
}

function KitCountPill({ icon: Icon, label, count }: { icon: React.ElementType; label: string; count: number }) {
  return (
    <span className="flex items-center gap-1.5 rounded-full border border-border bg-muted/30 px-2.5 py-1 text-xs text-muted-foreground">
      <Icon className="h-3 w-3" />
      <span className="font-medium text-foreground/80">{label}</span>
      <span className="text-[10px] rounded-full bg-sky-500/10 text-sky-400 px-1.5 py-0.5 font-semibold">
        {count}
      </span>
    </span>
  );
}

function TogglesList({ items }: { items: { label: string; enabled: boolean }[] }) {
  const [state, setState] = useState(items);
  return (
    <div className="space-y-2">
      {state.map((item, i) => (
        <div key={item.label} className="flex items-center justify-between rounded-md border border-border bg-muted/20 px-3 py-2.5">
          <span className="text-sm text-foreground">{item.label}</span>
          <button
            onClick={() =>
              setState((prev) => prev.map((x, idx) => (idx === i ? { ...x, enabled: !x.enabled } : x)))
            }
            className={cn(
              "relative h-5 w-9 rounded-full transition-colors",
              item.enabled ? "bg-primary" : "bg-muted"
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
                item.enabled ? "left-4" : "left-0.5"
              )}
            />
          </button>
        </div>
      ))}
    </div>
  );
}

function PreferenceRow({ item }: { item: { label: string; enabled: boolean; desc: string }; index: number }) {
  const [enabled, setEnabled] = useState(item.enabled);
  return (
    <div className="rounded-md border border-border bg-muted/20 px-3 py-2.5">
      <div className="flex items-center justify-between">
        <span className="text-sm text-foreground">{item.label}</span>
        <button
          onClick={() => setEnabled((v) => !v)}
          className={cn(
            "relative h-5 w-9 rounded-full transition-colors shrink-0",
            enabled ? "bg-primary" : "bg-muted"
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
              enabled ? "left-4" : "left-0.5"
            )}
          />
        </button>
      </div>
      <div className="text-[11px] text-muted-foreground mt-1 leading-snug">{item.desc}</div>
    </div>
  );
}

function PackageDetailDrawer({
  pkg,
  onClose,
  onCopy,
  copiedKey,
  onApproveAndPush,
}: {
  pkg: PublisherPackage;
  onClose: () => void;
  onCopy: (text: string, key: string, label?: string) => void;
  copiedKey: string | null;
  onApproveAndPush: () => void;
}) {
  return (
    <div className="fixed inset-0 z-40 flex">
      <button onClick={onClose} className="flex-1 bg-background/70 backdrop-blur-sm" aria-label="Close drawer" />
      <div className="w-[680px] max-w-[90vw] h-full bg-card border-l border-border shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 p-5 border-b border-border">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-medium", statusStyles[pkg.status])}>
                {statusLabel[pkg.status]}
              </span>
              <span className="text-[11px] text-muted-foreground font-mono">{pkg.videoId}</span>
            </div>
            <h2 className="text-base font-semibold text-foreground leading-snug">{pkg.videoTitle}</h2>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 h-8 w-8 flex items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          <Section title="Title variants" icon={Type}>
            <div className="space-y-1.5">
              {pkg.titleVariants.map((t, i) => (
                <BlockRow
                  key={i}
                  label={`${i + 1}`}
                  text={t}
                  ckey={`title-${pkg.id}-${i}`}
                  copiedKey={copiedKey}
                  onCopy={onCopy}
                  copyLabel="title"
                />
              ))}
            </div>
          </Section>

          <Section title="Description" icon={FileText} copyText={pkg.description} ckey={`desc-${pkg.id}`} onCopy={onCopy} copiedKey={copiedKey} copyLabel="description">
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground/90 bg-muted/20 border border-border rounded-md p-3">
              {pkg.description}
            </pre>
          </Section>

          <Section title="Tags" icon={Hash} copyText={pkg.tags.join(", ")} ckey={`tags-${pkg.id}`} onCopy={onCopy} copiedKey={copiedKey} copyLabel="tags">
            <div className="flex flex-wrap gap-1.5">
              {pkg.tags.map((t) => (
                <span key={t} className="rounded-full border border-border bg-muted/30 px-2.5 py-0.5 text-xs text-muted-foreground">
                  {t}
                </span>
              ))}
            </div>
          </Section>

          <Section title="Chapters" icon={ListOrdered} copyText={pkg.chapters.map(c => `${c.time} ${c.label}`).join("\n")} ckey={`chap-${pkg.id}`} onCopy={onCopy} copiedKey={copiedKey} copyLabel="chapters">
            <div className="rounded-md border border-border bg-muted/20 divide-y divide-border">
              {pkg.chapters.map((c) => (
                <div key={c.time} className="flex items-center gap-3 px-3 py-2">
                  <span className="font-mono text-xs text-sky-400 shrink-0">{c.time}</span>
                  <span className="text-sm text-foreground/90 flex-1">{c.label}</span>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Pinned comment" icon={MessageSquare} copyText={pkg.pinnedComment} ckey={`pin-${pkg.id}`} onCopy={onCopy} copiedKey={copiedKey} copyLabel="pinned comment">
            <div className="rounded-md border border-border bg-muted/20 p-3 text-sm text-foreground/90">
              {pkg.pinnedComment}
            </div>
          </Section>

          <Section title="Thumbnail text ideas" icon={ImageIcon}>
            <div className="space-y-1.5">
              {pkg.thumbnailIdeas.map((t, i) => (
                <BlockRow
                  key={i}
                  label={`${i + 1}`}
                  text={t}
                  ckey={`thumb-${pkg.id}-${i}`}
                  copiedKey={copiedKey}
                  onCopy={onCopy}
                  copyLabel="thumbnail idea"
                />
              ))}
            </div>
          </Section>

          {/* Divider */}
          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-border" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Social Kit</span>
            <div className="h-px flex-1 bg-border" />
          </div>

          <Section title="Tweets" icon={Send}>
            <div className="space-y-2">
              {pkg.socialKit.tweets.map((t, i) => (
                <BlockRow
                  key={i}
                  label={`Tweet ${i + 1}`}
                  text={t}
                  ckey={`tweet-${pkg.id}-${i}`}
                  copiedKey={copiedKey}
                  onCopy={onCopy}
                  copyLabel={`tweet ${i + 1}`}
                  multiline
                />
              ))}
            </div>
          </Section>

          <Section title="Thread outline" icon={MessageSquare} copyText={pkg.socialKit.threadOutline.map((t, i) => `${i + 1}. ${t}`).join("\n")} ckey={`thread-${pkg.id}`} onCopy={onCopy} copiedKey={copiedKey} copyLabel="thread">
            <ol className="space-y-1.5 list-none">
              {pkg.socialKit.threadOutline.map((t, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-foreground/90">
                  <span className="shrink-0 h-5 w-5 rounded-full bg-sky-500/10 text-sky-400 text-[10px] font-bold flex items-center justify-center mt-0.5">
                    {i + 1}
                  </span>
                  <span className="flex-1">{t}</span>
                </li>
              ))}
            </ol>
          </Section>

          <Section title="LinkedIn post" icon={Briefcase} copyText={pkg.socialKit.linkedin} ckey={`li-${pkg.id}`} onCopy={onCopy} copiedKey={copiedKey} copyLabel="LinkedIn post">
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground/90 bg-muted/20 border border-border rounded-md p-3">
              {pkg.socialKit.linkedin}
            </pre>
          </Section>

          <Section title="Instagram caption" icon={Camera} copyText={pkg.socialKit.instagram} ckey={`ig-${pkg.id}`} onCopy={onCopy} copiedKey={copiedKey} copyLabel="IG caption">
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground/90 bg-muted/20 border border-border rounded-md p-3">
              {pkg.socialKit.instagram}
            </pre>
          </Section>

          <Section title="Newsletter blurb" icon={Mail} copyText={pkg.socialKit.newsletter} ckey={`nl-${pkg.id}`} onCopy={onCopy} copiedKey={copiedKey} copyLabel="newsletter">
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground/90 bg-muted/20 border border-border rounded-md p-3">
              {pkg.socialKit.newsletter}
            </pre>
          </Section>
        </div>

        {/* Footer */}
        <div className="border-t border-border p-4 flex items-center gap-2 bg-card">
          <button
            onClick={() => onCopy(formatPackageAsText(pkg), `drawer-all-${pkg.id}`, "full kit")}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            {copiedKey === `drawer-all-${pkg.id}` ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
            Copy All
          </button>
          {pkg.status !== "pushed" && (
            <button
              onClick={onApproveAndPush}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-md bg-sky-500/10 border border-sky-500/30 px-3 py-2 text-sm font-medium text-sky-400 hover:bg-sky-500/20 transition-colors"
            >
              <Upload className="h-4 w-4" />
              {pkg.status === "pending" ? "Approve & Push" : "Push to YouTube"}
            </button>
          )}
          {pkg.status === "pushed" && (
            <a
              href={`https://studio.youtube.com/video/${pkg.videoId}/edit`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 flex items-center justify-center gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm font-medium text-emerald-400 hover:bg-emerald-500/10 transition-colors"
            >
              <ExternalLink className="h-4 w-4" />
              Open in YouTube Studio
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  icon: Icon,
  children,
  copyText,
  ckey,
  onCopy,
  copiedKey,
  copyLabel,
}: {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
  copyText?: string;
  ckey?: string;
  onCopy?: (text: string, key: string, label?: string) => void;
  copiedKey?: string | null;
  copyLabel?: string;
}) {
  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h3>
        </div>
        {copyText && ckey && onCopy && (
          <button
            onClick={() => onCopy(copyText, ckey, copyLabel)}
            className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {copiedKey === ckey ? (
              <>
                <Check className="h-3 w-3 text-emerald-400" /> Copied
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" /> Copy
              </>
            )}
          </button>
        )}
      </div>
      {children}
    </section>
  );
}

function BlockRow({
  label,
  text,
  ckey,
  copiedKey,
  onCopy,
  copyLabel,
  multiline,
}: {
  label: string;
  text: string;
  ckey: string;
  copiedKey: string | null;
  onCopy: (text: string, key: string, label?: string) => void;
  copyLabel?: string;
  multiline?: boolean;
}) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-border bg-muted/20 p-2.5">
      <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mt-1 w-14">{label}</span>
      {multiline ? (
        <pre className="flex-1 whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground/90">{text}</pre>
      ) : (
        <span className="flex-1 text-sm text-foreground/90">{text}</span>
      )}
      <button
        onClick={() => onCopy(text, ckey, copyLabel)}
        className="shrink-0 h-6 w-6 flex items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
      >
        {copiedKey === ckey ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
      </button>
    </div>
  );
}
