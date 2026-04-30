"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Calendar, GripVertical, Link2, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Shape of a task as the API returns it. Mirrors the relevant columns from
 * the `tasks` table — see packages/db/migrations/001_core.sql + 009_*.
 * The optional joined `agents` is from `?select=*,agents(...)` in the
 * list endpoint. Keep this loose-typed so future task fields don't require
 * a coordinated update; callers narrow as needed.
 */
export interface TaskRecord {
  id: string;
  org_id: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  type: string;
  position: number;
  deal_id: string | null;
  agent_id: string | null;
  project_id: string | null;
  due_at: string | null;
  created_by: string | null;
  created_at: string;
  agents?: {
    name: string;
    slug: string;
    icon: string | null;
  } | null;
}

interface TaskCardProps {
  task: TaskRecord;
  isDragging?: boolean;
  onClick?: () => void;
  onDelete?: () => void;
}

const PRIORITY_STYLES: Record<string, string> = {
  high: "border-red-500/40",
  medium: "border-amber-500/30",
  low: "border-zinc-500/20",
};

export function TaskCard({ task, isDragging, onClick, onDelete }: TaskCardProps) {
  // useSortable wires this card into dnd-kit's drag-drop system. Listeners
  // go on the drag handle (the GripVertical icon) — applying them to the
  // whole card would intercept clicks meant for the body.
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging: isSelfDragging,
  } = useSortable({ id: task.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    // The DragOverlay renders a floating card while dragging — hide the
    // source card so the user doesn't see a duplicate.
    opacity: isSelfDragging ? 0 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "group rounded-md border bg-card p-3 shadow-sm transition-colors",
        PRIORITY_STYLES[task.priority] ?? "border-border",
        isDragging ? "shadow-lg ring-2 ring-primary/40" : "hover:bg-accent/30",
      )}
    >
      <div className="flex items-start gap-2">
        {/* Drag handle — only this element listens for drag start so the
            rest of the card can be clickable for "open task" / "edit". */}
        <button
          {...attributes}
          {...listeners}
          aria-label="Drag task"
          className="cursor-grab text-muted-foreground/50 hover:text-muted-foreground active:cursor-grabbing"
        >
          <GripVertical className="h-3.5 w-3.5" />
        </button>

        <button
          onClick={onClick}
          className="flex-1 min-w-0 text-left"
          disabled={!onClick}
        >
          <p className="text-sm font-medium leading-snug text-foreground">
            {task.title}
          </p>
          {task.description && (
            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
              {task.description}
            </p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px]">
            {task.priority && task.priority !== "medium" && (
              <span
                className={cn(
                  "rounded-full border px-1.5 py-0.5 font-medium",
                  task.priority === "high"
                    ? "border-red-500/30 bg-red-500/10 text-red-400"
                    : "border-zinc-500/30 bg-zinc-500/10 text-zinc-400",
                )}
              >
                {task.priority}
              </span>
            )}

            {task.due_at && (
              <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/30 px-1.5 py-0.5 text-muted-foreground">
                <Calendar className="h-2.5 w-2.5" />
                {new Date(task.due_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                })}
              </span>
            )}

            {task.deal_id && (
              <span
                className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-primary"
                title="Linked to a brand deal"
              >
                <Link2 className="h-2.5 w-2.5" />
                Deal
              </span>
            )}

            {task.agents && (
              <span className="inline-flex items-center rounded-full border border-border bg-muted/30 px-1.5 py-0.5 text-muted-foreground">
                {task.agents.name}
              </span>
            )}
          </div>
        </button>

        {onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            aria-label="Delete task"
            className="text-muted-foreground/40 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>
    </div>
  );
}
