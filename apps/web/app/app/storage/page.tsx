"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  FolderOpen,
  Upload,
  Search,
  RefreshCw,
  Loader2,
  AlertCircle,
  X,
  Download,
  Trash2,
  Tag as TagIcon,
  FileText,
  Image as ImageIcon,
  Video,
  Music,
  Archive,
  RotateCcw,
  Plus,
  Check,
  File as FileIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const BUCKET = "org-assets";

type Asset = {
  id: string;
  org_id: string;
  storage_path: string;
  filename: string;
  size_bytes: number | null;
  mime_type: string | null;
  kind: AssetKind;
  tags: string[];
  source: string | null;
  source_id: string | null;
  uploaded_by: string | null;
  notes: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

type AssetKind =
  | "upload"
  | "brief"
  | "package"
  | "script"
  | "thumbnail"
  | "image"
  | "video"
  | "audio"
  | "other";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ok"; items: Asset[] };

type KindTab = "all" | AssetKind;

const KIND_TABS: { key: KindTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "upload", label: "Uploads" },
  { key: "brief", label: "Briefs" },
  { key: "package", label: "Packages" },
  { key: "script", label: "Scripts" },
  { key: "thumbnail", label: "Thumbnails" },
  { key: "image", label: "Images" },
  { key: "video", label: "Video" },
  { key: "audio", label: "Audio" },
];

// ── Helpers ───────────────────────────────────────────────────────────────

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

function formatSize(bytes: number | null): string {
  if (!bytes && bytes !== 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
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

function inferKind(file: File): AssetKind {
  const t = file.type;
  if (t.startsWith("image/")) return "image";
  if (t.startsWith("video/")) return "video";
  if (t.startsWith("audio/")) return "audio";
  return "upload";
}

function iconForKind(kind: AssetKind): React.ElementType {
  if (kind === "image" || kind === "thumbnail") return ImageIcon;
  if (kind === "video") return Video;
  if (kind === "audio") return Music;
  if (kind === "brief" || kind === "package" || kind === "script") return FileText;
  return FileIcon;
}

function colorForKind(kind: AssetKind): string {
  switch (kind) {
    case "image":
    case "thumbnail":
      return "text-pink-400 bg-pink-500/10 border-pink-500/20";
    case "video":
      return "text-violet-400 bg-violet-500/10 border-violet-500/20";
    case "audio":
      return "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
    case "brief":
      return "text-indigo-400 bg-indigo-500/10 border-indigo-500/20";
    case "package":
      return "text-sky-400 bg-sky-500/10 border-sky-500/20";
    case "script":
      return "text-amber-400 bg-amber-500/10 border-amber-500/20";
    default:
      return "text-muted-foreground bg-muted/30 border-border";
  }
}

// ── Page ──────────────────────────────────────────────────────────────────

export default function StoragePage() {
  const [list, setList] = useState<ListState>({ status: "loading" });
  const [kind, setKind] = useState<KindTab>("all");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [uploadProgress, setUploadProgress] = useState<{ name: string; pct: number }[]>([]);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const fetchList = useCallback(async () => {
    setList({ status: "loading" });
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setList({ status: "error", message: "Not signed in" });
        return;
      }
      const params = new URLSearchParams();
      if (kind !== "all") params.set("kind", kind);
      if (tagFilter) params.set("tag", tagFilter);
      if (search.trim()) params.set("search", search.trim());
      if (archived) params.set("archived", "true");
      const res = await fetch(`${API}/api/storage/assets?${params}`, { headers: auth });
      if (!res.ok) {
        setList({ status: "error", message: `HTTP ${res.status}` });
        return;
      }
      const items = (await res.json()) as Asset[];
      setList({ status: "ok", items });
      // Stash org_id for upload-path prefix construction.
      if (items[0]) setOrgId(items[0].org_id);
    } catch (e) {
      setList({ status: "error", message: (e as Error).message });
    }
  }, [kind, tagFilter, search, archived]);

  // Resolve org_id once even when list is empty, so first upload works.
  useEffect(() => {
    (async () => {
      if (orgId) return;
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;
      // Pull org_id via the org_members table the user is in. Same path
      // get_current_user uses on the API.
      const { data } = await supabase
        .from("org_members")
        .select("org_id")
        .eq("user_id", user.id)
        .limit(1);
      if (data?.[0]) setOrgId(data[0].org_id);
    })();
  }, [orgId]);

  useEffect(() => { fetchList(); }, [fetchList]);

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  // All tags currently in the list (for the tag filter chip rail)
  const allTags = useMemo(() => {
    if (list.status !== "ok") return [] as string[];
    const set = new Set<string>();
    for (const a of list.items) for (const t of a.tags ?? []) set.add(t);
    return Array.from(set).sort();
  }, [list]);

  // ── Upload handler ──────────────────────────────────────────────────────
  async function uploadFiles(files: File[]) {
    if (!orgId) {
      setToast("Couldn't resolve org — refresh and try again");
      return;
    }
    const supabase = createClient();
    const next = files.map((f) => ({ name: f.name, pct: 0 }));
    setUploadProgress((prev) => [...prev, ...next]);

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const detectedKind = inferKind(file);
      // Path: <org_id>/<kind>/<timestamp>-<filename>
      const ts = Date.now();
      const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, "_");
      const storagePath = `${orgId}/${detectedKind}/${ts}-${safeName}`;
      try {
        // Upload to Supabase Storage directly using the user's JWT.
        const { error } = await supabase.storage
          .from(BUCKET)
          .upload(storagePath, file, {
            contentType: file.type || undefined,
            cacheControl: "3600",
            upsert: false,
          });
        if (error) throw error;
        // Mark this file as fully uploaded
        setUploadProgress((prev) =>
          prev.map((p) => (p.name === file.name ? { ...p, pct: 100 } : p)),
        );
        // Register the asset row via the API
        const auth = await authHeader();
        const res = await fetch(`${API}/api/storage/assets`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...auth },
          body: JSON.stringify({
            storage_path: storagePath,
            filename: file.name,
            size_bytes: file.size,
            mime_type: file.type || null,
            kind: detectedKind,
            source: "user",
          }),
        });
        if (!res.ok) {
          throw new Error(`Register HTTP ${res.status}`);
        }
      } catch (e) {
        setToast(`Upload failed for ${file.name}: ${(e as Error).message}`);
      }
    }
    // Clear progress entries we just finished + refresh list
    setTimeout(() => {
      setUploadProgress((prev) => prev.filter((p) => p.pct < 100));
    }, 1200);
    fetchList();
  }

  return (
    <div className="flex h-full min-h-0">
      {/* Main */}
      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 border border-primary/20 mt-1">
            <FolderOpen className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">Storage</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Your org&apos;s shared library — uploads, agent exports, thumbnails, scripts. Everything addressable, taggable, downloadable.
            </p>
          </div>
          <UploadButton onFiles={uploadFiles} />
        </div>

        {/* Search + filters row */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[240px] max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by filename"
              className="w-full rounded-md border border-border bg-background pl-9 pr-3 py-2 text-sm placeholder:text-muted-foreground/70 focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
          <button
            onClick={() => setArchived((v) => !v)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs font-medium transition-colors",
              archived
                ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                : "border-border bg-card text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <Archive className="h-3.5 w-3.5" />
            {archived ? "Showing archived" : "Show archived"}
          </button>
          <button
            onClick={fetchList}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>

        {/* Kind tabs */}
        <div className="flex border-b border-border overflow-x-auto">
          {KIND_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setKind(tab.key)}
              className={cn(
                "px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap",
                kind === tab.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tag filter row */}
        {allTags.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-medium text-muted-foreground/80 uppercase tracking-wider">Tags:</span>
            {allTags.map((t) => (
              <button
                key={t}
                onClick={() => setTagFilter(tagFilter === t ? null : t)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                  tagFilter === t
                    ? "border-primary bg-primary/15 text-primary"
                    : "border-border bg-muted/30 text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <TagIcon className="h-2.5 w-2.5" />
                {t}
              </button>
            ))}
            {tagFilter && (
              <button
                onClick={() => setTagFilter(null)}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                Clear
              </button>
            )}
          </div>
        )}

        {/* Drag-drop zone (always visible, accepts files) */}
        <DropZone onFiles={uploadFiles} />

        {/* Grid */}
        <AssetGrid state={list} onSelect={setSelected} selectedId={selected?.id ?? null} />

        {/* Upload progress (bottom-fixed) */}
        {uploadProgress.length > 0 && (
          <div className="fixed bottom-6 left-6 z-30 w-72 rounded-lg border border-border bg-card/95 backdrop-blur p-3 shadow-lg space-y-2">
            <div className="text-xs font-medium text-foreground">Uploading…</div>
            {uploadProgress.map((p, i) => (
              <div key={i} className="space-y-1">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="truncate text-muted-foreground">{p.name}</span>
                  <span className="text-foreground font-mono">{p.pct}%</span>
                </div>
                <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full rounded-full bg-primary transition-all"
                    style={{ width: `${p.pct}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Right detail panel */}
      {selected && (
        <DetailPanel
          asset={selected}
          onClose={() => setSelected(null)}
          onChanged={(updated) => {
            // Reflect the update into the visible list + re-select
            if (list.status === "ok") {
              setList({
                status: "ok",
                items: list.items.map((a) => (a.id === updated.id ? updated : a)),
              });
            }
            setSelected(updated);
          }}
          onDeleted={(id) => {
            if (list.status === "ok") {
              setList({
                status: "ok",
                items: list.items.filter((a) => a.id !== id),
              });
            }
            setSelected(null);
            setToast("Moved to archive");
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
    </div>
  );
}

// ── UploadButton ──────────────────────────────────────────────────────────

function UploadButton({ onFiles }: { onFiles: (files: File[]) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        onClick={() => inputRef.current?.click()}
        className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors"
      >
        <Upload className="h-4 w-4" />
        Upload
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          e.target.value = "";
        }}
      />
    </>
  );
}

// ── DropZone ──────────────────────────────────────────────────────────────

function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setHover(true);
      }}
      onDragLeave={() => setHover(false)}
      onDrop={(e) => {
        e.preventDefault();
        setHover(false);
        const files = Array.from(e.dataTransfer.files ?? []);
        if (files.length) onFiles(files);
      }}
      className={cn(
        "rounded-lg border border-dashed p-6 text-center text-sm transition-colors",
        hover
          ? "border-primary bg-primary/5 text-primary"
          : "border-border bg-muted/10 text-muted-foreground",
      )}
    >
      <Upload className="h-5 w-5 mx-auto mb-2 opacity-70" />
      Drag and drop files here, or use the Upload button.
    </div>
  );
}

// ── AssetGrid ─────────────────────────────────────────────────────────────

function AssetGrid({
  state,
  onSelect,
  selectedId,
}: {
  state: ListState;
  onSelect: (a: Asset) => void;
  selectedId: string | null;
}) {
  if (state.status === "loading") {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-12 text-center">
        <Loader2 className="h-6 w-6 text-muted-foreground animate-spin mx-auto mb-2" />
        <div className="text-sm text-muted-foreground">Loading…</div>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-5">
        <div className="flex items-center gap-2 mb-1">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-sm font-medium text-red-400">Couldn&apos;t load assets</span>
        </div>
        <div className="text-xs text-muted-foreground">{state.message}</div>
      </div>
    );
  }
  if (state.items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/10 p-12 text-center">
        <FolderOpen className="h-6 w-6 text-muted-foreground mx-auto mb-2" />
        <div className="text-sm text-foreground font-medium">Nothing here yet</div>
        <div className="text-xs text-muted-foreground mt-1">
          Drop files above to upload your first asset.
        </div>
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
      {state.items.map((a) => (
        <AssetCard
          key={a.id}
          asset={a}
          selected={selectedId === a.id}
          onClick={() => onSelect(a)}
        />
      ))}
    </div>
  );
}

function AssetCard({
  asset,
  selected,
  onClick,
}: {
  asset: Asset;
  selected: boolean;
  onClick: () => void;
}) {
  const Icon = iconForKind(asset.kind);
  const color = colorForKind(asset.kind);
  return (
    <button
      onClick={onClick}
      className={cn(
        "text-left rounded-lg border bg-card p-4 transition-colors hover:border-primary/40",
        selected ? "border-primary ring-1 ring-primary" : "border-border",
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-md border", color)}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-foreground truncate">{asset.filename}</div>
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground mt-0.5">
            <span className="capitalize">{asset.kind}</span>
            <span>·</span>
            <span>{formatSize(asset.size_bytes)}</span>
          </div>
        </div>
      </div>
      {asset.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-3">
          {asset.tags.slice(0, 4).map((t) => (
            <span
              key={t}
              className="rounded-full border border-border bg-muted/30 px-1.5 py-0 text-[10px] text-muted-foreground"
            >
              {t}
            </span>
          ))}
          {asset.tags.length > 4 && (
            <span className="text-[10px] text-muted-foreground">+{asset.tags.length - 4}</span>
          )}
        </div>
      )}
      <div className="text-[10px] text-muted-foreground mt-3 flex items-center justify-between">
        <span>{relativeTime(asset.created_at)}</span>
        {asset.source && asset.source !== "user" && (
          <span className="rounded-full border border-border px-1.5 py-0 text-[10px] capitalize">
            {asset.source.replace("-", " ")}
          </span>
        )}
      </div>
    </button>
  );
}

// ── DetailPanel ───────────────────────────────────────────────────────────

function DetailPanel({
  asset,
  onClose,
  onChanged,
  onDeleted,
}: {
  asset: Asset;
  onClose: () => void;
  onChanged: (a: Asset) => void;
  onDeleted: (id: string) => void;
}) {
  const [filename, setFilename] = useState(asset.filename);
  const [tags, setTags] = useState<string[]>(asset.tags);
  const [pendingTag, setPendingTag] = useState("");
  const [notes, setNotes] = useState(asset.notes ?? "");
  const [busy, setBusy] = useState<null | "save" | "download" | "delete" | "restore">(null);

  // Reset draft state when a different asset is selected
  useEffect(() => {
    setFilename(asset.filename);
    setTags(asset.tags);
    setNotes(asset.notes ?? "");
    setPendingTag("");
  }, [asset.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const isDirty =
    filename !== asset.filename ||
    notes !== (asset.notes ?? "") ||
    tags.length !== asset.tags.length ||
    tags.some((t, i) => t !== asset.tags[i]);

  async function save() {
    setBusy("save");
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/storage/assets/${asset.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify({ filename, tags, notes: notes.trim() || null }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = (await res.json()) as Asset;
      onChanged(updated);
    } catch (e) {
      alert(`Save failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function download() {
    setBusy("download");
    try {
      const auth = await authHeader();
      const res = await fetch(
        `${API}/api/storage/assets/${asset.id}/download-url?expires_in=300`,
        { headers: auth },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { url } = (await res.json()) as { url: string };
      // Trigger a download by navigating to the signed URL.
      const a = document.createElement("a");
      a.href = url;
      a.download = asset.filename;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      alert(`Download failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function archive() {
    if (!confirm(`Archive "${asset.filename}"?`)) return;
    setBusy("delete");
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/storage/assets/${asset.id}`, {
        method: "DELETE",
        headers: auth,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onDeleted(asset.id);
    } catch (e) {
      alert(`Archive failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function restore() {
    setBusy("restore");
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/storage/assets/${asset.id}/restore`, {
        method: "POST",
        headers: auth,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = (await res.json()) as Asset;
      onChanged(updated);
    } catch (e) {
      alert(`Restore failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  function commitTag() {
    const v = pendingTag.trim();
    if (!v) return;
    if (!tags.includes(v)) setTags([...tags, v]);
    setPendingTag("");
  }

  const Icon = iconForKind(asset.kind);
  const color = colorForKind(asset.kind);
  const isImage = (asset.mime_type ?? "").startsWith("image/");

  return (
    <div className="w-96 shrink-0 border-l border-border bg-card/50 overflow-y-auto p-5 space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border", color)}>
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground truncate">{asset.filename}</div>
            <div className="text-[11px] text-muted-foreground capitalize">{asset.kind}</div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {isImage && (
        <ImagePreview asset={asset} />
      )}

      {/* Filename edit */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-foreground">Name</label>
        <input
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Tags */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-foreground">Tags</label>
        <div className="flex flex-wrap gap-1.5">
          {tags.map((t, i) => (
            <span
              key={`${t}-${i}`}
              className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11px] text-primary"
            >
              {t}
              <button
                onClick={() => setTags(tags.filter((_, j) => j !== i))}
                className="text-primary/60 hover:text-primary"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
          {tags.length === 0 && (
            <span className="text-[11px] text-muted-foreground italic">No tags yet</span>
          )}
        </div>
        <div className="flex gap-2">
          <input
            value={pendingTag}
            onChange={(e) => setPendingTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                commitTag();
              }
            }}
            placeholder="Add tag and press Enter"
            className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <button
            onClick={commitTag}
            disabled={!pendingTag.trim()}
            className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Notes */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-foreground">Notes</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="What is this for? When was it written?"
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs resize-y focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Metadata */}
      <div className="rounded-md border border-border bg-muted/20 p-3 space-y-1.5 text-[11px] text-muted-foreground">
        <Meta k="Size" v={formatSize(asset.size_bytes)} />
        <Meta k="MIME" v={asset.mime_type ?? "—"} />
        <Meta k="Source" v={asset.source ?? "user"} />
        <Meta k="Uploaded" v={new Date(asset.created_at).toLocaleString()} />
        <Meta k="Path" v={asset.storage_path} mono truncate />
      </div>

      {/* Actions */}
      <div className="space-y-2">
        <button
          onClick={download}
          disabled={busy !== null}
          className="w-full inline-flex items-center justify-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium text-foreground hover:bg-accent transition-colors disabled:opacity-60"
        >
          {busy === "download" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          Download
        </button>
        {isDirty && (
          <button
            onClick={save}
            disabled={busy !== null}
            className="w-full inline-flex items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-60"
          >
            {busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Save changes
          </button>
        )}
        {asset.archived_at ? (
          <button
            onClick={restore}
            disabled={busy !== null}
            className="w-full inline-flex items-center justify-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-400 hover:bg-emerald-500/20 transition-colors disabled:opacity-60"
          >
            {busy === "restore" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
            Restore from archive
          </button>
        ) : (
          <button
            onClick={archive}
            disabled={busy !== null}
            className="w-full inline-flex items-center justify-center gap-2 rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2 text-sm font-medium text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-60"
          >
            {busy === "delete" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            Archive
          </button>
        )}
      </div>
    </div>
  );
}

function Meta({ k, v, mono, truncate }: { k: string; v: string; mono?: boolean; truncate?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-foreground/70 shrink-0">{k}</span>
      <span
        className={cn(
          "text-right",
          mono && "font-mono",
          truncate && "truncate min-w-0",
        )}
        title={v}
      >
        {v}
      </span>
    </div>
  );
}

function ImagePreview({ asset }: { asset: Asset }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const auth = await authHeader();
      const res = await fetch(
        `${API}/api/storage/assets/${asset.id}/download-url?expires_in=600`,
        { headers: auth },
      );
      if (!res.ok) return;
      const { url } = (await res.json()) as { url: string };
      if (!cancelled) setUrl(url);
    })();
    return () => { cancelled = true; };
  }, [asset.id]);

  if (!url) {
    return (
      <div className="aspect-video rounded-md border border-dashed border-border bg-muted/20 flex items-center justify-center">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return (
    <div className="aspect-video rounded-md border border-border bg-muted overflow-hidden">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt={asset.filename} className="h-full w-full object-cover" />
    </div>
  );
}
