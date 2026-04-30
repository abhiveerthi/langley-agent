"use client";

import { useDroppable } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { Plus } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * A Kanban column that's also a droppable zone. Wraps its children in a
 * SortableContext so each card can use `useSortable` to participate in
 * within-column reordering. The droppable id is `column:<key>` so the
 * board's onDragEnd can detect drops onto an empty column (no card to
 * use as the drop target).
 */
interface KanbanColumnProps {
  columnKey: string;
  label: string;
  accent?: string;
  count: number;
  itemIds: string[];
  onAdd?: () => void;
  children: React.ReactNode;
}

export function KanbanColumn({
  columnKey,
  label,
  accent,
  count,
  itemIds,
  onAdd,
  children,
}: KanbanColumnProps) {
  // Droppable id for empty-column drops. When a card is dragged over an
  // empty column, no item-id is below the cursor — this id is what
  // dnd-kit's collision detection lands on.
  const { isOver, setNodeRef } = useDroppable({ id: `column:${columnKey}` });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex w-72 shrink-0 flex-col rounded-lg border bg-muted/20 transition-colors",
        isOver ? "border-primary/50 bg-primary/5" : "border-border",
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={cn(
              "text-xs font-semibold uppercase tracking-wider",
              accent ?? "text-muted-foreground",
            )}
          >
            {label}
          </span>
          <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-muted px-1.5 text-xs font-medium text-muted-foreground">
            {count}
          </span>
        </div>
        {onAdd && (
          <button
            onClick={onAdd}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            title={`Add to ${label}`}
            aria-label={`Add task to ${label}`}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {/* Cards */}
      <SortableContext items={itemIds} strategy={verticalListSortingStrategy}>
        <div className="flex-1 space-y-2 p-2 min-h-32">
          {count === 0 ? (
            <div className="flex h-20 items-center justify-center rounded-md border border-dashed border-border text-xs text-muted-foreground">
              {isOver ? "Drop here" : "Empty"}
            </div>
          ) : (
            children
          )}
        </div>
      </SortableContext>
    </div>
  );
}
