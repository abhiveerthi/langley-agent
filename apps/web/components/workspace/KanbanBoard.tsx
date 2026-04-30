"use client";

import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
  DragOverlay,
} from "@dnd-kit/core";
import { useState } from "react";
import { KanbanColumn } from "./KanbanColumn";

/**
 * Generic Kanban container — knows about columns and items, leaves the
 * card rendering to the caller via `renderCard`. Same component will
 * back the To-Dos board on /app/tasks AND (eventually) the Brand Manager
 * dashboard's deal Kanban — only the columns + cards differ.
 *
 * Drag-drop semantics:
 *   - Drop a card onto a different column → `onMove(itemId, newColumn, position)`
 *     fires with the destination column key and the new sort position.
 *   - Drop within the same column → reorder within column, same callback fires.
 *   - The parent owns the items array and decides how to apply the move
 *     (optimistic vs server-roundtrip-then-update). This component does
 *     NOT mutate state itself — pure controlled input.
 */

export interface KanbanItem {
  id: string;
  status: string;
  position: number;
}

export interface KanbanColumnDef {
  /** Status string that matches `item.status` for items in this column. */
  key: string;
  /** Human label shown in the column header. */
  label: string;
  /** Optional accent color class for the header (Tailwind utility). */
  accent?: string;
}

interface KanbanBoardProps<T extends KanbanItem> {
  columns: KanbanColumnDef[];
  items: T[];
  /** Render a single card. Caller controls the visual + click handlers. */
  renderCard: (item: T, opts: { isDragging: boolean }) => React.ReactNode;
  /**
   * Fired when an item is moved. Position is the index within the destination
   * column's current items (zero-based) — use it to resolve a sort_order
   * value the API understands.
   */
  onMove: (itemId: string, toColumnKey: string, toIndex: number) => void;
  /** Optional "+ add" button per column header. */
  onAddItem?: (columnKey: string) => void;
}

export function KanbanBoard<T extends KanbanItem>({
  columns,
  items,
  renderCard,
  onMove,
  onAddItem,
}: KanbanBoardProps<T>) {
  // Track which item is being dragged so we can render a DragOverlay (the
  // floating card that follows the cursor during drag). Without this the
  // dragged card just disappears from its source column mid-drag, which
  // looks broken.
  const [activeId, setActiveId] = useState<string | null>(null);
  const activeItem = items.find((i) => i.id === activeId);

  // PointerSensor with a small activation distance — prevents stray clicks
  // (e.g. "edit task" click on a card) from registering as a drag.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  function handleDragStart(event: DragStartEvent) {
    setActiveId(String(event.active.id));
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveId(null);
    const { active, over } = event;
    if (!over) return;

    const activeIdStr = String(active.id);
    const overIdStr = String(over.id);
    const activeItem = items.find((i) => i.id === activeIdStr);
    if (!activeItem) return;

    // dnd-kit IDs we use:
    //   - item ids (real task UUIDs)
    //   - column "drop zones" with id `column:<key>` for empty-column drops
    //
    // If `over` is another item, the drop target column = that item's column.
    // If `over` is a `column:<key>` zone, the drop target = that column.
    let toColumnKey: string;
    let toIndex: number;

    if (overIdStr.startsWith("column:")) {
      toColumnKey = overIdStr.slice("column:".length);
      // Drop at end of empty-or-otherwise column.
      const inColumn = items.filter(
        (i) => i.status === toColumnKey && i.id !== activeIdStr,
      );
      toIndex = inColumn.length;
    } else {
      const overItem = items.find((i) => i.id === overIdStr);
      if (!overItem) return;
      toColumnKey = overItem.status;
      const inColumn = items
        .filter((i) => i.status === toColumnKey && i.id !== activeIdStr)
        .sort((a, b) => a.position - b.position);
      toIndex = inColumn.findIndex((i) => i.id === overIdStr);
      if (toIndex === -1) toIndex = inColumn.length;
    }

    // Skip no-op move (same column, same neighbor).
    if (
      activeItem.status === toColumnKey &&
      sameRelativePosition(items, activeItem, toColumnKey, toIndex)
    ) {
      return;
    }

    onMove(activeIdStr, toColumnKey, toIndex);
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="flex gap-4 overflow-x-auto pb-4">
        {columns.map((col) => {
          const colItems = items
            .filter((i) => i.status === col.key)
            .sort((a, b) => a.position - b.position);
          return (
            <KanbanColumn
              key={col.key}
              columnKey={col.key}
              label={col.label}
              accent={col.accent}
              count={colItems.length}
              itemIds={colItems.map((i) => i.id)}
              onAdd={onAddItem ? () => onAddItem(col.key) : undefined}
            >
              {colItems.map((item) =>
                renderCard(item, { isDragging: item.id === activeId }),
              )}
            </KanbanColumn>
          );
        })}
      </div>

      <DragOverlay>
        {activeItem ? renderCard(activeItem, { isDragging: false }) : null}
      </DragOverlay>
    </DndContext>
  );
}

function sameRelativePosition<T extends KanbanItem>(
  items: T[],
  active: T,
  toColumnKey: string,
  toIndex: number,
): boolean {
  const inColumn = items
    .filter((i) => i.status === toColumnKey)
    .sort((a, b) => a.position - b.position);
  const currentIndex = inColumn.findIndex((i) => i.id === active.id);
  return currentIndex === toIndex;
}
