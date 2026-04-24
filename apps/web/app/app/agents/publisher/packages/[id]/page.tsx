"use client";

import Link from "next/link";
import { useEffect, useState, useCallback, useMemo, use } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import {
  ArrowLeft,
  Video,
  ExternalLink,
  Loader2,
  RefreshCw,
  Upload as UploadIcon,
  Check,
  X as XIcon,
  AlertCircle,
  Sparkles,
  Type,
  Hash,
  ListOrdered,
  MessageSquare,
  Image as ImageIcon,
  Send,
  Mail,
  Copy,
  Pencil,
  CircleDot,
  Circle,
  Trash2,
  RotateCcw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  PublisherPackage,
  PublisherApproval,
  RegenField,
} from "@/lib/types/publisher";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

const statusStyles: Record<PublisherPackage["status"], string> = {
  generating:   "bg-sky-500/10 text-sky-400 border-sky-500/20",
  draft:        "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
  pending_push: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  pushed:       "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
};

const statusLabel: Record<PublisherPackage["status"], string> = {
  generating:   "Generating…",
  draft:        "Draft",
  pending_push: "Awaiting Approval",
  pushed:       "Pushed to YouTube",
};

export default function PackageDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();

  const [pkg, setPkg] = useState<PublisherPackage | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [regenField, setRegenField] = useState<RegenField | null>(null);
  const [approval, setApproval] = useState<PublisherApproval | null>(null);
  const [showApprovalDialog, setShowApprovalDialog] = useState(false);
  const [rejectFeedback, setRejectFeedback] = useState("");
  const [acting, setActing] = useState<"approve" | "reject" | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [pushPending, setPushPending] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState<null | "regen-all" | "delete">(null);
  const [bulkActing, setBulkActing] = useState(false);
  // Track approval IDs we've already auto-opened — so if the user dismisses
  // the dialog, polling doesn't keep reopening it on the same row.
  const [openedApprovalIds, setOpenedApprovalIds] = useState<Set<string>>(new Set());

  // ── Fetchers ──────────────────────────────────────────────────────────
  const fetchPackage = useCallback(async () => {
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/publisher/packages/${id}`, { headers: auth });
      if (res.status === 404) {
        setErr("Package not found");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as PublisherPackage;
      setPkg(data);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [id]);

  const fetchApproval = useCallback(async () => {
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/publisher/packages/${id}/approval`, { headers: auth });
      if (!res.ok) return;
      const data = await res.json();
      setApproval(data as PublisherApproval | null);
    } catch {
      // ignore — approval is optional
    }
  }, [id]);

  // Initial load
  useEffect(() => {
    fetchPackage();
  }, [fetchPackage]);

  // Poll while the row is in flight: still generating, mid-push, OR we just
  // fired the push button and are waiting for the approval_gate row to land.
  // `pushPending` is the key: without it there's a race where the UI stops
  // polling before the agent has flipped status to pending_push.
  const needsPolling = useMemo(() => {
    if (!pkg) return true; // still loading
    if (pushPending) return true;
    return pkg.status === "generating" || pkg.status === "pending_push";
  }, [pkg, pushPending]);

  useEffect(() => {
    if (!needsPolling) return;
    const interval = setInterval(() => {
      fetchPackage();
      // Always try fetching the approval during a polling window — cheap, and
      // avoids a stale-closure race on pkg.status.
      fetchApproval();
    }, 2000);
    return () => clearInterval(interval);
  }, [needsPolling, fetchPackage, fetchApproval]);

  // Clear `pushPending` once the approval has arrived or the flow completed.
  useEffect(() => {
    if (!pushPending) return;
    if (approval && approval.status === "pending") setPushPending(false);
    else if (pkg?.status === "pushed") setPushPending(false);
  }, [pushPending, approval, pkg?.status]);

  // When a regen run is in progress, poll to see when the field changes
  useEffect(() => {
    if (!regenField) return;
    const interval = setInterval(() => fetchPackage(), 1500);
    return () => clearInterval(interval);
  }, [regenField, fetchPackage]);

  // Clear regenField once the package has updated (new updated_at on that field)
  const [regenStartedAt, setRegenStartedAt] = useState<string | null>(null);
  useEffect(() => {
    if (!regenField || !regenStartedAt || !pkg) return;
    if (pkg.updated_at > regenStartedAt) {
      setRegenField(null);
      setRegenStartedAt(null);
      setToast(`Regenerated ${regenField.replace("social.", "").replace("_", " ")}`);
    }
  }, [pkg, regenField, regenStartedAt]);

  // Auto-open approval dialog the FIRST time a new pending approval arrives.
  // We remember the approval id we opened so a user-dismissed dialog doesn't
  // re-open on every poll tick. A fresh approval (e.g. from reject → revise
  // loop) has a new id so it will still auto-open.
  useEffect(() => {
    if (!approval || approval.status !== "pending") return;
    if (openedApprovalIds.has(approval.id)) return;
    setShowApprovalDialog(true);
    setOpenedApprovalIds((prev) => {
      const next = new Set(prev);
      next.add(approval.id);
      return next;
    });
  }, [approval, openedApprovalIds]);

  // Auto-dismiss toast
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

  // ── Actions ───────────────────────────────────────────────────────────
  async function regenerate(field: RegenField) {
    if (!pkg || regenField) return;
    setRegenField(field);
    setRegenStartedAt(pkg.updated_at);
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/publisher/packages/${pkg.id}/regenerate`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ field }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      setToast(`Regenerate failed: ${(e as Error).message}`);
      setRegenField(null);
      setRegenStartedAt(null);
    }
  }

  async function pushPackage(selectedTitle?: string) {
    if (!pkg) return;
    setPushPending(true);
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/publisher/packages/${pkg.id}/push`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ selected_title: selectedTitle ?? null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setToast("Preparing push — waiting for your approval");
      fetchPackage();
    } catch (e) {
      setToast(`Push failed: ${(e as Error).message}`);
      setPushPending(false);
    }
  }

  /**
   * Drain the SSE body so the server-side task finishes its work.
   * Canceling (.cancel()) aborts mid-graph, which can leave the approval
   * status flipped but the downstream push/revise never runs.
   */
  async function drainStream(res: Response) {
    const reader = res.body?.getReader();
    if (!reader) return;
    while (true) {
      const { done } = await reader.read();
      if (done) break;
    }
  }

  async function approvePush() {
    if (!approval) return;
    setActing("approve");
    // Close the dialog immediately for responsiveness — the server-side flip
    // to status=approved means polling won't find this row again.
    setShowApprovalDialog(false);
    setToast("Pushing to YouTube…");
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/approvals/${approval.id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await drainStream(res);
      setApproval(null);
      fetchPackage();
    } catch (e) {
      setToast(`Approve failed: ${(e as Error).message}`);
    } finally {
      setActing(null);
    }
  }

  async function rejectPush() {
    if (!approval) return;
    setActing("reject");
    setShowApprovalDialog(false);
    setToast("Rejected — Publisher is revising");
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/approvals/${approval.id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ feedback: rejectFeedback || null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await drainStream(res);
      setApproval(null);
      setRejectFeedback("");
      // After drain, the revise loop has paused at a new approval_gate; poll
      // picks it up and auto-opens (new id, so not in openedApprovalIds).
      fetchApproval();
      fetchPackage();
    } catch (e) {
      setToast(`Reject failed: ${(e as Error).message}`);
    } finally {
      setActing(null);
    }
  }

  async function copy(text: string, key: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
    } catch {
      setToast("Copy failed");
    }
  }

  /** PATCH one or more fields on the package, then merge into local state. */
  async function patchPackage(patch: Record<string, unknown>, toastLabel?: string) {
    if (!pkg) return;
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/publisher/packages/${pkg.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify(patch),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = (await res.json()) as PublisherPackage;
      setPkg(updated);
      if (toastLabel) setToast(toastLabel);
    } catch (e) {
      setToast(`Save failed: ${(e as Error).message}`);
    }
  }

  /** Re-run the full generation flow on this package id. */
  async function regenerateAll() {
    if (!pkg || bulkActing) return;
    setBulkActing(true);
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/publisher/packages/${pkg.id}/regenerate-all`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setToast("Regenerating entire package…");
      setConfirmOpen(null);
      fetchPackage(); // pick up the new generating status immediately
    } catch (e) {
      setToast(`Regenerate failed: ${(e as Error).message}`);
    } finally {
      setBulkActing(false);
    }
  }

  /** Delete the package row and return to the list. */
  async function deletePackage() {
    if (!pkg || bulkActing) return;
    setBulkActing(true);
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/publisher/packages/${pkg.id}`, {
        method: "DELETE",
        headers: auth,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      router.push("/app/agents/publisher");
    } catch (e) {
      setToast(`Delete failed: ${(e as Error).message}`);
      setBulkActing(false);
    }
  }

  /** Mark a title variant as the chosen one by moving it to index 0. */
  async function chooseTitle(title: string) {
    if (!pkg) return;
    if (pkg.title_variants[0] === title) return; // already chosen
    const reordered = [title, ...pkg.title_variants.filter((t) => t !== title)];
    await patchPackage({ title_variants: reordered }, "Selected as push title");
  }

  // ── Render ────────────────────────────────────────────────────────────
  if (err) {
    return (
      <div className="p-6">
        <Link href="/app/agents/publisher" className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3">
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to Publisher
        </Link>
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-5">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="h-4 w-4 text-red-400" />
            <span className="text-sm font-medium text-red-400">{err}</span>
          </div>
        </div>
      </div>
    );
  }
  if (!pkg) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-dashed border-border bg-muted/10 p-8 text-center">
          <Loader2 className="h-6 w-6 text-muted-foreground animate-spin mx-auto mb-2" />
          <div className="text-sm text-muted-foreground">Loading package…</div>
        </div>
      </div>
    );
  }

  const isGenerating = pkg.status === "generating";
  const canPush = pkg.status === "draft";

  return (
    <div className="flex h-full min-h-0 overflow-y-auto">
      <div className="flex-1 p-6 max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <Link
            href="/app/agents/publisher"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Publisher
          </Link>
          <div className="flex items-start gap-4">
            <div className="flex h-14 w-24 shrink-0 items-center justify-center rounded-md bg-linear-to-br from-sky-500/20 to-indigo-500/20 border border-border">
              <Video className="h-5 w-5 text-sky-400" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-xl font-semibold text-foreground truncate">{pkg.video_title}</h1>
              <div className="text-xs text-muted-foreground mt-1 font-mono">{pkg.video_id}</div>
              <div className="flex items-center gap-3 mt-2">
                <span className={cn("rounded-full border px-2.5 py-0.5 text-[11px] font-medium", statusStyles[pkg.status])}>
                  {isGenerating && <Loader2 className="inline h-3 w-3 animate-spin mr-1" />}
                  {statusLabel[pkg.status]}
                </span>
                {pkg.warning && (
                  <span className="inline-flex items-center gap-1 text-[11px] text-amber-400">
                    <AlertCircle className="h-3 w-3" />
                    {pkg.warning}
                  </span>
                )}
                <a
                  href={`https://studio.youtube.com/video/${pkg.video_id}/edit`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
                >
                  <ExternalLink className="h-3 w-3" />
                  Open in Studio
                </a>
              </div>
            </div>
            {canPush && (
              <button
                onClick={() => pushPackage(pkg.title_variants[0])}
                className="shrink-0 flex items-center gap-1.5 rounded-md bg-sky-500/10 border border-sky-500/30 px-4 py-2 text-sm font-medium text-sky-400 hover:bg-sky-500/20 transition-colors"
              >
                <UploadIcon className="h-4 w-4" />
                Push to YouTube
              </button>
            )}
            {pkg.status === "pending_push" && approval && (
              <button
                onClick={() => setShowApprovalDialog(true)}
                className="shrink-0 flex items-center gap-1.5 rounded-md bg-amber-500/10 border border-amber-500/30 px-4 py-2 text-sm font-medium text-amber-400 hover:bg-amber-500/20 transition-colors"
              >
                <AlertCircle className="h-4 w-4" />
                Review Push
              </button>
            )}
          </div>

          {/* Package-level actions */}
          <div className="flex items-center justify-end gap-2 mt-3">
            <button
              onClick={() => setConfirmOpen("regen-all")}
              disabled={isGenerating || bulkActing}
              className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Regenerate entire package
            </button>
            <button
              onClick={() => setConfirmOpen("delete")}
              disabled={bulkActing}
              className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-red-500/10 hover:border-red-500/30 hover:text-red-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete package
            </button>
          </div>
        </div>

        {/* Title variants — each row has a radio to mark it as the push title */}
        <TitleVariantsSection
          pkg={pkg}
          onRegen={() => regenerate("title_variants")}
          regenActive={regenField === "title_variants"}
          disabled={isGenerating}
          onChoose={chooseTitle}
          onSave={async (items) => patchPackage({ title_variants: items }, "Titles updated")}
          copiedKey={copiedKey}
          onCopy={copy}
        />

        <EditableSection
          title="Description"
          icon={MessageSquare}
          kind="text"
          value={pkg.description || ""}
          placeholder="(empty)"
          skeletonLabel="Writing description…"
          isGenerating={isGenerating && !pkg.description}
          onSave={async (v) => patchPackage({ description: v as string }, "Description saved")}
          onRegen={() => regenerate("description")}
          regenActive={regenField === "description"}
          disabled={isGenerating}
          copyText={pkg.description || ""}
          copyKey="description"
          copiedKey={copiedKey}
          onCopy={copy}
        />

        <EditableSection
          title="Tags"
          icon={Hash}
          kind="list-commas"
          value={pkg.tags}
          placeholder="comma-separated, mix of broad + long-tail"
          skeletonLabel="Gathering tags…"
          isGenerating={isGenerating && pkg.tags.length === 0}
          onSave={async (v) => patchPackage({ tags: v as string[] }, "Tags saved")}
          onRegen={() => regenerate("tags")}
          regenActive={regenField === "tags"}
          disabled={isGenerating}
          copyText={pkg.tags.join(", ")}
          copyKey="tags"
          copiedKey={copiedKey}
          onCopy={copy}
        />

        <EditableSection
          title="Chapters"
          icon={ListOrdered}
          kind="chapters"
          value={pkg.chapters}
          placeholder="0:00 Intro"
          skeletonLabel="Pulling chapters from transcript…"
          isGenerating={isGenerating && pkg.chapters.length === 0}
          onSave={async (v) => patchPackage({ chapters: v as { time: string; label: string }[] }, "Chapters saved")}
          onRegen={() => regenerate("chapters")}
          regenActive={regenField === "chapters"}
          disabled={isGenerating}
          copyText={pkg.chapters.map((c) => `${c.time} ${c.label}`).join("\n")}
          copyKey="chapters"
          copiedKey={copiedKey}
          onCopy={copy}
        />

        <EditableSection
          title="Thumbnail Ideas"
          icon={ImageIcon}
          kind="list-newlines"
          value={pkg.thumbnail_ideas}
          placeholder="One overlay idea per line"
          skeletonLabel="Generating thumbnail overlay ideas…"
          isGenerating={isGenerating && pkg.thumbnail_ideas.length === 0}
          onSave={async (v) => patchPackage({ thumbnail_ideas: v as string[] }, "Thumbnails saved")}
          onRegen={() => regenerate("thumbnail_ideas")}
          regenActive={regenField === "thumbnail_ideas"}
          disabled={isGenerating}
          copyText={pkg.thumbnail_ideas.join("\n")}
          copyKey="thumbnails"
          copiedKey={copiedKey}
          onCopy={copy}
        />

        {/* Socials */}
        <div className="rounded-lg border border-border bg-card/50 p-5 space-y-4">
          <div className="text-sm font-semibold text-foreground">Social Drafts</div>

          <EditableSection
            variant="inline"
            title="X / Twitter"
            icon={Send}
            kind="text"
            value={pkg.social.twitter || ""}
            placeholder="A single tweet, ≤ 280 chars"
            skeletonLabel="Writing tweet…"
            isGenerating={isGenerating && !pkg.social.twitter}
            onSave={async (v) =>
              patchPackage({ social: { ...pkg.social, twitter: v as string } }, "Tweet saved")
            }
            onRegen={() => regenerate("social.twitter")}
            regenActive={regenField === "social.twitter"}
            disabled={isGenerating}
            copyText={pkg.social.twitter || ""}
            copyKey="social-twitter"
            copiedKey={copiedKey}
            onCopy={copy}
          />

          <EditableSection
            variant="inline"
            title="Newsletter"
            icon={Mail}
            kind="text"
            value={pkg.social.newsletter || ""}
            placeholder="80–120 word blurb"
            skeletonLabel="Writing newsletter blurb…"
            isGenerating={isGenerating && !pkg.social.newsletter}
            onSave={async (v) =>
              patchPackage({ social: { ...pkg.social, newsletter: v as string } }, "Newsletter saved")
            }
            onRegen={() => regenerate("social.newsletter")}
            regenActive={regenField === "social.newsletter"}
            disabled={isGenerating}
            copyText={pkg.social.newsletter || ""}
            copyKey="social-newsletter"
            copiedKey={copiedKey}
            onCopy={copy}
          />
        </div>

        {pkg.status === "pushed" && pkg.youtube_pushed_at && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 flex items-center gap-3">
            <Check className="h-5 w-5 text-emerald-400" />
            <div className="flex-1 text-sm text-foreground">
              Pushed to YouTube on {new Date(pkg.youtube_pushed_at).toLocaleString()}.
            </div>
            <a
              href={`https://studio.youtube.com/video/${pkg.video_id}/edit`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-emerald-400 hover:underline"
            >
              View in Studio →
            </a>
          </div>
        )}
      </div>

      {/* Confirmation dialog for regen-all / delete */}
      {confirmOpen && (
        <ConfirmDialog
          kind={confirmOpen}
          busy={bulkActing}
          onCancel={() => setConfirmOpen(null)}
          onConfirm={confirmOpen === "regen-all" ? regenerateAll : deletePackage}
        />
      )}

      {/* Approval dialog */}
      {showApprovalDialog && approval && (
        <ApprovalDialog
          approval={approval}
          onClose={() => setShowApprovalDialog(false)}
          onApprove={approvePush}
          onReject={rejectPush}
          rejectFeedback={rejectFeedback}
          onFeedbackChange={setRejectFeedback}
          acting={acting}
        />
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 rounded-lg border border-border bg-card/95 backdrop-blur px-4 py-2.5 shadow-lg flex items-center gap-2">
          <Check className="h-4 w-4 text-emerald-400" />
          <span className="text-sm text-foreground">{toast}</span>
        </div>
      )}
    </div>
  );
}

// ── Layout helpers ──────────────────────────────────────────────────────

type EditKind = "text" | "list-newlines" | "list-commas" | "chapters";
type EditableValue = string | string[] | { time: string; label: string }[];

function serialize(kind: EditKind, value: EditableValue): string {
  if (kind === "text") return (value as string) || "";
  if (kind === "list-newlines") return (value as string[]).join("\n");
  if (kind === "list-commas") return (value as string[]).join(", ");
  // chapters
  return (value as { time: string; label: string }[])
    .map((c) => `${c.time} ${c.label}`)
    .join("\n");
}

function parse(kind: EditKind, text: string): EditableValue {
  if (kind === "text") return text;
  if (kind === "list-newlines") {
    return text.split("\n").map((s) => s.trim()).filter(Boolean);
  }
  if (kind === "list-commas") {
    return text.split(",").map((s) => s.trim()).filter(Boolean);
  }
  // chapters — format: "MM:SS label" or "H:MM:SS label" per line
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const m = line.match(/^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$/);
      return m ? { time: m[1], label: m[2] } : null;
    })
    .filter((c): c is { time: string; label: string } => c !== null);
}

function isEmpty(kind: EditKind, value: EditableValue): boolean {
  if (kind === "text") return !(value as string);
  return (value as Array<unknown>).length === 0;
}

function Skeleton({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/20 border border-dashed border-border rounded-md px-3 py-4">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      {label}
    </div>
  );
}

function EditableSection({
  title,
  icon: Icon,
  kind,
  value,
  placeholder,
  skeletonLabel,
  isGenerating,
  onSave,
  onRegen,
  regenActive,
  disabled,
  copyText,
  copyKey,
  copiedKey,
  onCopy,
  variant = "outer",
}: {
  title: string;
  icon: React.ElementType;
  kind: EditKind;
  value: EditableValue;
  placeholder: string;
  skeletonLabel: string;
  isGenerating: boolean;
  onSave: (value: EditableValue) => Promise<void>;
  onRegen?: () => void;
  regenActive?: boolean;
  disabled?: boolean;
  copyText?: string;
  copyKey?: string;
  copiedKey?: string | null;
  onCopy?: (text: string, key: string) => void;
  /** "outer" — bordered card (default). "inline" — no border, for nesting inside other cards. */
  variant?: "outer" | "inline";
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  function enter() {
    setDraft(serialize(kind, value));
    setEditing(true);
  }
  function cancel() {
    setEditing(false);
    setDraft("");
  }
  async function save() {
    setSaving(true);
    try {
      await onSave(parse(kind, draft));
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  const wrapperClass =
    variant === "outer"
      ? "rounded-lg border border-border bg-card/50 p-5"
      : "";

  return (
    <section className={wrapperClass}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
          <h3 className={cn(
            variant === "outer" ? "text-sm font-semibold text-foreground" : "text-xs font-semibold uppercase tracking-wider text-muted-foreground",
          )}>
            {title}
          </h3>
        </div>
        <div className="flex items-center gap-1">
          {!editing && copyText && copyKey && onCopy && copyText.length > 0 && (
            <button
              onClick={() => onCopy(copyText, copyKey)}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            >
              {copiedKey === copyKey ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
            </button>
          )}
          {!editing && (
            <button
              onClick={enter}
              disabled={disabled || regenActive}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Pencil className="h-3 w-3" />
              Edit
            </button>
          )}
          {!editing && onRegen && (
            <button
              onClick={onRegen}
              disabled={disabled || regenActive}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <RefreshCw className={cn("h-3 w-3", regenActive && "animate-spin")} />
              {regenActive ? "Regenerating…" : "Regenerate"}
            </button>
          )}
          {editing && (
            <>
              <button
                onClick={cancel}
                disabled={saving}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="flex items-center gap-1 rounded-md bg-sky-500/10 border border-sky-500/30 px-2 py-1 text-[11px] text-sky-400 hover:bg-sky-500/20 transition-colors disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                Save
              </button>
            </>
          )}
        </div>
      </div>

      {editing ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          className="w-full rounded-md border border-sky-500/30 bg-muted/10 px-3 py-2 text-sm text-foreground font-mono placeholder:text-muted-foreground focus:border-sky-500/60 focus:outline-none resize-y min-h-24"
          rows={kind === "text" ? 6 : 5}
          autoFocus
        />
      ) : isGenerating ? (
        <Skeleton label={skeletonLabel} />
      ) : isEmpty(kind, value) ? (
        <div className="text-xs text-muted-foreground italic">(empty)</div>
      ) : (
        <ViewBody kind={kind} value={value} />
      )}
    </section>
  );
}

function ViewBody({ kind, value }: { kind: EditKind; value: EditableValue }) {
  if (kind === "text") {
    return (
      <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground/90 bg-muted/20 border border-border rounded-md p-3">
        {value as string}
      </pre>
    );
  }
  if (kind === "list-commas") {
    return (
      <div className="flex flex-wrap gap-1.5">
        {(value as string[]).map((t, i) => (
          <span key={i} className="rounded-md border border-border bg-muted/30 px-2 py-0.5 text-xs text-foreground/80">
            {t}
          </span>
        ))}
      </div>
    );
  }
  if (kind === "list-newlines") {
    return (
      <div className="space-y-1.5">
        {(value as string[]).map((t, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground w-4">{i + 1}</span>
            <span className="flex-1 text-sm text-foreground/90">{t}</span>
          </div>
        ))}
      </div>
    );
  }
  // chapters
  return (
    <div className="space-y-1">
      {(value as { time: string; label: string }[]).map((c, i) => (
        <div key={i} className="flex items-center gap-3 text-sm">
          <span className="font-mono text-xs text-muted-foreground w-14">{c.time}</span>
          <span className="flex-1 text-foreground/90">{c.label}</span>
        </div>
      ))}
    </div>
  );
}

// ── Title variants with selectable "push title" ─────────────────────────

function TitleVariantsSection({
  pkg,
  onRegen,
  regenActive,
  disabled,
  onChoose,
  onSave,
  copiedKey,
  onCopy,
}: {
  pkg: PublisherPackage;
  onRegen: () => void;
  regenActive: boolean;
  disabled: boolean;
  onChoose: (title: string) => Promise<void>;
  onSave: (items: string[]) => Promise<void>;
  copiedKey: string | null;
  onCopy: (text: string, key: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const items = pkg.title_variants;
  const chosen = items[0] || null;

  function enter() {
    setDraft(items.join("\n"));
    setEditing(true);
  }
  function cancel() {
    setEditing(false);
    setDraft("");
  }
  async function save() {
    setSaving(true);
    try {
      const parsed = draft.split("\n").map((s) => s.trim()).filter(Boolean);
      await onSave(parsed);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card/50 p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Type className="h-3.5 w-3.5 text-muted-foreground" />
          <h3 className="text-sm font-semibold text-foreground">Title Variants</h3>
          {chosen && !editing && (
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              · pick one for push
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {!editing && (
            <>
              <button
                onClick={enter}
                disabled={disabled || regenActive}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Pencil className="h-3 w-3" />
                Edit
              </button>
              <button
                onClick={onRegen}
                disabled={disabled || regenActive}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <RefreshCw className={cn("h-3 w-3", regenActive && "animate-spin")} />
                {regenActive ? "Regenerating…" : "Regenerate"}
              </button>
            </>
          )}
          {editing && (
            <>
              <button
                onClick={cancel}
                disabled={saving}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="flex items-center gap-1 rounded-md bg-sky-500/10 border border-sky-500/30 px-2 py-1 text-[11px] text-sky-400 hover:bg-sky-500/20 transition-colors disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                Save
              </button>
            </>
          )}
        </div>
      </div>

      {editing ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="One title per line. The first one after save is the push title."
          className="w-full rounded-md border border-sky-500/30 bg-muted/10 px-3 py-2 text-sm text-foreground font-mono placeholder:text-muted-foreground focus:border-sky-500/60 focus:outline-none resize-y min-h-24"
          rows={5}
          autoFocus
        />
      ) : items.length === 0 ? (
        <Skeleton label="Writing titles…" />
      ) : (
        <div className="space-y-1.5">
          {items.map((t, i) => {
            const isChosen = t === chosen;
            return (
              <div key={i} className="flex items-center gap-2">
                <button
                  onClick={() => onChoose(t)}
                  className="shrink-0 text-muted-foreground hover:text-sky-400 transition-colors"
                  title={isChosen ? "Selected for push" : "Use this title on push"}
                >
                  {isChosen ? (
                    <CircleDot className="h-4 w-4 text-sky-400" />
                  ) : (
                    <Circle className="h-4 w-4" />
                  )}
                </button>
                <span className={cn("flex-1 text-sm", isChosen ? "text-foreground" : "text-foreground/80")}>{t}</span>
                <button
                  onClick={() => onCopy(t, `title-${i}`)}
                  className="shrink-0 h-6 w-6 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground"
                >
                  {copiedKey === `title-${i}` ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Confirm dialog (regen-all / delete) ─────────────────────────────────

function ConfirmDialog({
  kind,
  busy,
  onCancel,
  onConfirm,
}: {
  kind: "regen-all" | "delete";
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const isDelete = kind === "delete";
  const title = isDelete ? "Delete this package?" : "Regenerate entire package?";
  const body = isDelete
    ? "This removes the package from your library. The video on YouTube is untouched — if you've already pushed metadata to YouTube, that stays. This can't be undone."
    : "Publisher will re-fetch the transcript and rewrite every field from scratch. The current kit stays visible until the new one overwrites it (~30–45s).";
  const confirmLabel = isDelete ? "Delete" : "Regenerate";
  const ConfirmIcon = isDelete ? Trash2 : RotateCcw;
  const confirmClass = isDelete
    ? "bg-red-500/10 border-red-500/30 text-red-400 hover:bg-red-500/20"
    : "bg-sky-500/10 border-sky-500/30 text-sky-400 hover:bg-sky-500/20";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-6">
      <div className="w-full max-w-md rounded-lg border border-border bg-card shadow-xl">
        <div className="p-5 border-b border-border">
          <h2 className="text-base font-semibold text-foreground">{title}</h2>
          <p className="text-sm text-muted-foreground mt-2">{body}</p>
        </div>
        <div className="p-4 flex items-center justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={busy}
            className="rounded-md border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50",
              confirmClass,
            )}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ConfirmIcon className="h-4 w-4" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Approval dialog ─────────────────────────────────────────────────────

function ApprovalDialog({
  approval,
  onClose,
  onApprove,
  onReject,
  rejectFeedback,
  onFeedbackChange,
  acting,
}: {
  approval: PublisherApproval;
  onClose: () => void;
  onApprove: () => void;
  onReject: () => void;
  rejectFeedback: string;
  onFeedbackChange: (v: string) => void;
  acting: "approve" | "reject" | null;
}) {
  const p = approval.action_payload;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-6">
      <div className="w-full max-w-2xl max-h-full overflow-y-auto rounded-lg border border-border bg-card shadow-xl">
        <div className="p-5 border-b border-border flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-amber-400 mb-1">
              <AlertCircle className="h-4 w-4" />
              <span className="text-xs font-semibold uppercase tracking-wider">Approval Required</span>
            </div>
            <h2 className="text-lg font-semibold text-foreground">Push metadata to YouTube</h2>
            <p className="text-xs text-muted-foreground mt-1">{approval.preview}</p>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 h-8 w-8 flex items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <DiffRow label="Title" current={p.current_title} proposed={p.proposed_title} />
          <DiffRow label="Tags" current={(p.current_tags || []).join(", ")} proposed={(p.proposed_tags || []).join(", ")} />
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">Description</div>
            <details className="rounded-md border border-border bg-muted/20">
              <summary className="px-3 py-2 text-xs text-muted-foreground cursor-pointer">Preview (click to expand)</summary>
              <pre className="px-3 pb-3 whitespace-pre-wrap font-sans text-xs text-foreground/80 max-h-48 overflow-y-auto">
                {p.proposed_description}
              </pre>
            </details>
          </div>

          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5 block">
              Feedback (optional, used on reject)
            </label>
            <textarea
              value={rejectFeedback}
              onChange={(e) => onFeedbackChange(e.target.value)}
              placeholder="e.g. less clickbaity, shorter tags…"
              className="w-full rounded-md border border-border bg-muted/20 px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-sky-500/40 focus:outline-none"
              rows={2}
            />
          </div>
        </div>

        <div className="p-5 border-t border-border flex items-center justify-end gap-2">
          <button
            onClick={onReject}
            disabled={acting !== null}
            className="flex items-center gap-1.5 rounded-md border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:text-red-400 hover:border-red-500/30 transition-colors disabled:opacity-50"
          >
            {acting === "reject" ? <Loader2 className="h-4 w-4 animate-spin" /> : <XIcon className="h-4 w-4" />}
            Reject & revise
          </button>
          <button
            onClick={onApprove}
            disabled={acting !== null}
            className="flex items-center gap-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/30 px-4 py-2 text-sm font-medium text-emerald-400 hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
          >
            {acting === "approve" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Approve & push
          </button>
        </div>
      </div>
    </div>
  );
}

function DiffRow({
  label,
  current,
  proposed,
}: {
  label: string;
  current: string;
  proposed: string;
}) {
  const changed = (current || "") !== (proposed || "");
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">{label}</div>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div className="rounded-md border border-border bg-muted/20 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Current</div>
          <div className="text-foreground/80 wrap-break-word">{current || <span className="text-muted-foreground italic">(empty)</span>}</div>
        </div>
        <div className={cn(
          "rounded-md border px-3 py-2",
          changed ? "border-sky-500/30 bg-sky-500/5" : "border-border bg-muted/20",
        )}>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1 flex items-center gap-1">
            Proposed {changed && <Sparkles className="h-2.5 w-2.5 text-sky-400" />}
          </div>
          <div className="text-foreground wrap-break-word">{proposed || <span className="text-muted-foreground italic">(empty)</span>}</div>
        </div>
      </div>
    </div>
  );
}
