"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2, Plus, RefreshCw } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { KanbanBoard, type KanbanColumnDef } from "@/components/workspace/KanbanBoard";
import { TaskCard, type TaskRecord } from "@/components/workspace/TaskCard";
import { NewTaskModal } from "@/components/workspace/NewTaskModal";
import { cn } from "@/lib/utils";
import { useStaleWhileRevalidate } from "@/lib/swr";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const DEFAULT_STATUSES = ["todo", "in_progress", "blocked", "done"];
const STATUSES_CACHE_KEY = "workspace.statuses";

const STATUS_LABELS: Record<string, string> = {
  todo: "To Do",
  in_progress: "In Progress",
  blocked: "Blocked",
  done: "Done",
  cancelled: "Cancelled",
  pending: "To Do", // legacy default mapped to first column
};

const STATUS_ACCENTS: Record<string, string> = {
  todo: "text-zinc-400",
  in_progress: "text-amber-400",
  blocked: "text-red-400",
  done: "text-emerald-400",
  cancelled: "text-muted-foreground",
};

type LoadState =
  | { state: "loading" }
  | { state: "ready" }
  | { state: "error"; message: string };

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

export default function TasksPage() {
  const params = useSearchParams();
  const dealFilter = params.get("deal_id"); // optional ?deal_id=... from BM dashboard

  // Statuses change rarely (settings UI edit); SWR-cache them in localStorage
  // so the Kanban columns paint instantly on subsequent visits — even before
  // /api/tasks responds. The cached value is revalidated in the background.
  const fetchStatuses = useCallback(async (): Promise<string[]> => {
    const headers = { ...(await authHeader()) };
    const res = await fetch(`${API}/api/workspace/statuses`, { headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as { statuses: string[] };
    if (!Array.isArray(data.statuses) || data.statuses.length === 0) {
      return DEFAULT_STATUSES;
    }
    return data.statuses;
  }, []);
  const { data: statuses } = useStaleWhileRevalidate<string[]>(
    STATUSES_CACHE_KEY,
    fetchStatuses,
  );

  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [load, setLoad] = useState<LoadState>({ state: "loading" });
  const [modalOpen, setModalOpen] = useState(false);
  const [modalDefaultStatus, setModalDefaultStatus] = useState("todo");

  const fetchTasks = useCallback(async () => {
    const params = new URLSearchParams();
    if (dealFilter) params.set("deal_id", dealFilter);
    const headers = { ...(await authHeader()) };
    const url = `${API}/api/tasks${params.toString() ? `?${params}` : ""}`;
    const res = await fetch(url, { headers });
    if (!res.ok) {
      setLoad({ state: "error", message: `HTTP ${res.status}` });
      return;
    }
    const rows = (await res.json()) as TaskRecord[];
    setTasks(rows);
    setLoad({ state: "ready" });
  }, [dealFilter]);

  useEffect(() => {
    // Defer to a microtask so we don't trip the React 19
    // `react-hooks/set-state-in-effect` lint — same pattern as the
    // approvals page. Statuses are handled by useStaleWhileRevalidate
    // above, so only tasks need to fire here.
    queueMicrotask(() => {
      void fetchTasks();
    });
  }, [fetchTasks]);

  // Build the column defs from the org's status list. Falls back to the
  // standard set when statuses haven't loaded yet (first ever visit).
  const columns: KanbanColumnDef[] = ((statuses && statuses.length) ? statuses : DEFAULT_STATUSES).map(
    (key) => ({
      key,
      label: STATUS_LABELS[key] ?? prettify(key),
      accent: STATUS_ACCENTS[key],
    }),
  );

  /**
   * Handle a drag-drop. Optimistically update the local list (so the
   * card lands instantly), then PATCH the server. On failure, refetch to
   * snap back to the source-of-truth.
   */
  const handleMove = useCallback(
    async (itemId: string, toColumnKey: string, toIndex: number) => {
      // Compute the new position. We use (toIndex * 1000) so there's room
      // between rows and we rarely have to renumber the column. If a column
      // gets very dense over time, a future fix could rebalance.
      const newPosition = toIndex * 1000;

      // Optimistic update.
      setTasks((prev) =>
        prev.map((t) =>
          t.id === itemId
            ? { ...t, status: toColumnKey, position: newPosition }
            : t,
        ),
      );

      try {
        const headers = {
          "Content-Type": "application/json",
          ...(await authHeader()),
        };
        const res = await fetch(`${API}/api/tasks/${itemId}`, {
          method: "PATCH",
          headers,
          body: JSON.stringify({
            status: toColumnKey,
            position: newPosition,
          }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch {
        // Rollback by refetching authoritative state.
        await fetchTasks();
      }
    },
    [fetchTasks],
  );

  async function handleCreate(input: {
    title: string;
    description: string | null;
    priority: string;
    status: string;
    due_at: string | null;
    deal_id: string | null;
  }) {
    const headers = {
      "Content-Type": "application/json",
      ...(await authHeader()),
    };
    // Compute initial position = 0 so the new task lands at the top of the
    // chosen column. The next drag will renumber if needed.
    const res = await fetch(`${API}/api/tasks`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        title: input.title,
        description: input.description,
        status: input.status,
        priority: input.priority,
        due_at: input.due_at,
        deal_id: input.deal_id ?? dealFilter,
        position: 0,
      }),
    });
    if (res.ok) {
      const row = (await res.json()) as TaskRecord;
      setTasks((prev) => [row, ...prev]);
      setModalOpen(false);
    }
  }

  async function handleDelete(taskId: string) {
    const headers = await authHeader();
    const res = await fetch(`${API}/api/tasks/${taskId}`, {
      method: "DELETE",
      headers,
    });
    if (res.ok) {
      setTasks((prev) => prev.filter((t) => t.id !== taskId));
    }
  }

  function openCreate(forStatus: string) {
    setModalDefaultStatus(forStatus);
    setModalOpen(true);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between border-b border-border px-6 pb-4 pt-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Tasks</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {dealFilter
              ? "Tasks linked to this deal"
              : "Drag to move between columns. New tasks default to the column you click on."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => fetchTasks()}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
          <button
            onClick={() => openCreate(columns[0]?.key ?? "todo")}
            className="flex items-center gap-2 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            New task
          </button>
        </div>
      </div>

      <div className={cn("flex-1 overflow-x-auto px-6 py-4", load.state === "loading" && "opacity-50")}>
        {load.state === "loading" && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </div>
        )}
        {load.state === "error" && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            Couldn&apos;t load tasks: {load.message}
          </div>
        )}
        {load.state === "ready" && (
          <KanbanBoard
            columns={columns}
            items={tasks.map((t) => ({
              ...t,
              // Older tasks default to "pending" — show them in the first column
              // so they don't disappear behind a status no current column shows.
              status: t.status === "pending" ? "todo" : t.status,
            }))}
            onMove={handleMove}
            onAddItem={openCreate}
            renderCard={(task, { isDragging }) => (
              <TaskCard
                key={task.id}
                task={task as TaskRecord}
                isDragging={isDragging}
                onDelete={() => handleDelete(task.id)}
              />
            )}
          />
        )}
      </div>

      <NewTaskModal
        open={modalOpen}
        defaultStatus={modalDefaultStatus}
        defaultDealId={dealFilter ?? undefined}
        onClose={() => setModalOpen(false)}
        onCreate={handleCreate}
      />
    </div>
  );
}

function prettify(slug: string): string {
  return slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
