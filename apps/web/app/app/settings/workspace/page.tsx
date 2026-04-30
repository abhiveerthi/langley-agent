"use client";

import { useCallback, useEffect, useState } from "react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Loader2, Plus, Save, Trash2, AlertCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const STATUS_RE = /^[a-z0-9_]{1,32}$/;
const MAX_STATUSES = 12;

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

function slugify(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[^a-z0-9_]/g, "")
    .slice(0, 32);
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready" };

export default function WorkspaceSettingsPage() {
  const [statuses, setStatuses] = useState<string[]>([]);
  const [savedStatuses, setSavedStatuses] = useState<string[]>([]);
  const [loadState, setLoadState] = useState<LoadState>({ kind: "loading" });
  const [draftNew, setDraftNew] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const fetchStatuses = useCallback(async () => {
    setLoadState({ kind: "loading" });
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setLoadState({ kind: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/workspace/statuses`, { headers: auth });
      if (!res.ok) {
        setLoadState({ kind: "error", message: `HTTP ${res.status}` });
        return;
      }
      const body = (await res.json()) as { statuses: string[] };
      setStatuses(body.statuses);
      setSavedStatuses(body.statuses);
      setLoadState({ kind: "ready" });
    } catch (e) {
      setLoadState({ kind: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void fetchStatuses();
    });
  }, [fetchStatuses]);

  const isDirty = JSON.stringify(statuses) !== JSON.stringify(savedStatuses);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = statuses.indexOf(String(active.id));
    const newIndex = statuses.indexOf(String(over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    setStatuses((prev) => arrayMove(prev, oldIndex, newIndex));
  }

  function handleAdd() {
    const slug = slugify(draftNew);
    if (!slug) return;
    if (!STATUS_RE.test(slug)) return;
    if (statuses.includes(slug)) {
      setDraftNew("");
      return;
    }
    if (statuses.length >= MAX_STATUSES) return;
    setStatuses((prev) => [...prev, slug]);
    setDraftNew("");
  }

  function handleRemove(status: string) {
    if (statuses.length <= 1) return; // schema requires ≥1
    setStatuses((prev) => prev.filter((s) => s !== status));
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    try {
      const auth = await authHeader();
      const res = await fetch(`${API}/api/workspace/statuses`, {
        method: "PUT",
        headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify({ statuses }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        setSaveError(detail.detail ?? `HTTP ${res.status}`);
        return;
      }
      const body = (await res.json()) as { statuses: string[] };
      setSavedStatuses(body.statuses);
      setStatuses(body.statuses);
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function handleDiscard() {
    setStatuses(savedStatuses);
    setSaveError(null);
  }

  return (
    <div className="max-w-2xl">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-foreground">Workspace columns</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The columns that appear on <span className="font-medium text-foreground">/app/tasks</span> for your team. Drag to reorder, add new ones for your workflow (QA, Review, Scheduled…), or remove any you don&apos;t use.
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          Tasks already in a removed column aren&apos;t deleted — they show under{" "}
          <span className="font-mono">Other</span> on the board so you can re-route them.
        </p>
      </div>

      {loadState.kind === "loading" && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {loadState.kind === "error" && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-400">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4" />
            Couldn&apos;t load — {loadState.message}
          </div>
        </div>
      )}

      {loadState.kind === "ready" && (
        <>
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext items={statuses} strategy={verticalListSortingStrategy}>
              <ul className="space-y-2">
                {statuses.map((s) => (
                  <SortableRow
                    key={s}
                    status={s}
                    canRemove={statuses.length > 1}
                    onRemove={() => handleRemove(s)}
                  />
                ))}
              </ul>
            </SortableContext>
          </DndContext>

          {/* Add new */}
          <div className="mt-4 flex gap-2">
            <input
              value={draftNew}
              onChange={(e) => setDraftNew(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleAdd();
              }}
              placeholder="Add a column (e.g. qa, review, scheduled)"
              disabled={statuses.length >= MAX_STATUSES}
              className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none disabled:opacity-50"
            />
            <button
              onClick={handleAdd}
              disabled={!slugify(draftNew) || statuses.length >= MAX_STATUSES}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Plus className="h-3.5 w-3.5" />
              Add
            </button>
          </div>
          {statuses.length >= MAX_STATUSES && (
            <p className="mt-2 text-xs text-muted-foreground">
              Maximum of {MAX_STATUSES} columns. Remove one to add another.
            </p>
          )}
          {draftNew && draftNew !== slugify(draftNew) && (
            <p className="mt-2 text-xs text-muted-foreground">
              Will save as <span className="font-mono text-foreground">{slugify(draftNew)}</span> — column keys must be lowercase letters, numbers, or underscores.
            </p>
          )}

          {/* Save bar */}
          <div className="mt-6 flex items-center justify-between gap-3 rounded-lg border border-border bg-card p-4">
            <div className="text-xs text-muted-foreground">
              {isDirty ? (
                <span className="text-amber-400">Unsaved changes</span>
              ) : (
                "All changes saved"
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleDiscard}
                disabled={!isDirty || saving}
                className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
              >
                Discard
              </button>
              <button
                onClick={handleSave}
                disabled={!isDirty || saving}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                Save
              </button>
            </div>
          </div>

          {saveError && (
            <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-400">
              <AlertCircle className="mr-1.5 inline h-3.5 w-3.5" />
              {saveError}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function SortableRow({
  status,
  canRemove,
  onRemove,
}: {
  status: string;
  canRemove: boolean;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: status });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <li
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2"
    >
      <button
        {...attributes}
        {...listeners}
        className="cursor-grab text-muted-foreground hover:text-foreground active:cursor-grabbing"
        aria-label={`Drag ${status}`}
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <span className="flex-1 font-mono text-sm text-foreground">{status}</span>
      <button
        onClick={onRemove}
        disabled={!canRemove}
        className="rounded p-1 text-muted-foreground hover:bg-red-500/10 hover:text-red-400 disabled:opacity-30 disabled:cursor-not-allowed"
        aria-label={`Remove ${status}`}
        title={canRemove ? `Remove ${status}` : "At least one column is required"}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </li>
  );
}
