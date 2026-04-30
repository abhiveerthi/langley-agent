"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Building2, Clock, GripVertical, Mail } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Brand deal as the API returns it — see `brand_deals` table schema in
 * packages/db/migrations/006_brand_deals.sql.
 *
 * Stage is the source of truth for "which Kanban column" — the page maps
 * it via the `KanbanItem.status` field.
 */
export interface DealRecord {
  id: string;
  org_id: string;
  brand_name: string;
  recipient: string | null;
  subject: string | null;
  stage: "pitched" | "replied" | "negotiating" | "signed" | "declined" | "paused";
  external_message_id: string | null;
  notes: string | null;
  pitched_at: string | null;
  last_updated_at: string;
}

interface DealCardProps {
  deal: DealRecord;
  isDragging?: boolean;
  onClick?: () => void;
}

export function DealCard({ deal, isDragging, onClick }: DealCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging: isSelfDragging,
  } = useSortable({ id: deal.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isSelfDragging ? 0 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "group rounded-md border border-border bg-card p-3 shadow-sm transition-colors",
        isDragging ? "shadow-lg ring-2 ring-primary/40" : "hover:bg-accent/30",
      )}
    >
      <div className="flex items-start gap-2">
        {/* Drag handle — same pattern as TaskCard so card-body clicks
            (future: open deal detail) aren't intercepted. */}
        <button
          {...attributes}
          {...listeners}
          aria-label="Drag deal"
          className="mt-0.5 cursor-grab text-muted-foreground/50 hover:text-muted-foreground active:cursor-grabbing"
        >
          <GripVertical className="h-3.5 w-3.5" />
        </button>

        <button
          onClick={onClick}
          className="flex-1 min-w-0 text-left"
          disabled={!onClick}
        >
          <div className="flex items-center gap-2 mb-1">
            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-amber-500/10">
              <Building2 className="h-3 w-3 text-amber-400" />
            </div>
            <span className="truncate text-sm font-medium text-foreground">
              {deal.brand_name}
            </span>
          </div>

          {deal.subject && (
            <p className="line-clamp-2 text-xs text-muted-foreground">
              {deal.subject}
            </p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
            {deal.recipient && (
              <span className="inline-flex items-center gap-1 truncate max-w-[140px]">
                <Mail className="h-2.5 w-2.5" />
                {deal.recipient}
              </span>
            )}
            <span className="inline-flex items-center gap-1">
              <Clock className="h-2.5 w-2.5" />
              {relativeTime(deal.last_updated_at)}
            </span>
          </div>
        </button>
      </div>
    </div>
  );
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
