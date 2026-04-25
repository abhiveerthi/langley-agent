"use client";

import { Compass, Sparkles, TrendingUp, AlertCircle } from "lucide-react";
import type { WeeklyBrief, VideoIdea } from "@/hooks/useChat";
import { cn } from "@/lib/utils";

interface BriefCardProps {
  brief: WeeklyBrief;
}

/**
 * Renders Strategist's WeeklyBrief — the headline + ranked video ideas
 * with hook / why-now / confidence / citations. Surfaces alongside the
 * markdown chat reply (see MessageBubble) when the orchestrator emits a
 * `structured_output` event of kind "brief".
 *
 * Schema authority: packages/agents/strategist/agent.py:WeeklyBrief.
 */
export function BriefCard({ brief }: BriefCardProps) {
  return (
    <div className="rounded-lg border border-primary/20 bg-card overflow-hidden">
      {/* Headline row */}
      <div className="border-b border-primary/15 bg-primary/5 px-5 py-4">
        <div className="flex items-start gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/15">
            <Compass className="h-4 w-4 text-primary" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-primary">
              Weekly Brief
            </p>
            <p className="mt-1 text-sm font-medium leading-snug text-foreground">
              {brief.headline}
            </p>
          </div>
        </div>
      </div>

      {/* Ranked ideas */}
      <div className="divide-y divide-border">
        {brief.ideas.map((idea, i) => (
          <IdeaRow key={`${idea.title}-${i}`} idea={idea} rank={i + 1} />
        ))}
        {brief.ideas.length === 0 && (
          <div className="px-5 py-6 text-center text-xs text-muted-foreground">
            No ranked ideas in this brief.
          </div>
        )}
      </div>
    </div>
  );
}

const CONFIDENCE_STYLES: Record<VideoIdea["confidence"], string> = {
  high: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  medium: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  low: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
};

function IdeaRow({ idea, rank }: { idea: VideoIdea; rank: number }) {
  return (
    <div className="px-5 py-4">
      {/* Title + rank + confidence */}
      <div className="mb-2 flex items-start gap-3">
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-semibold text-muted-foreground">
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-snug text-foreground">
            {idea.title}
          </p>
        </div>
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-[10px] font-medium",
            CONFIDENCE_STYLES[idea.confidence] ?? CONFIDENCE_STYLES.medium
          )}
        >
          {idea.confidence}
        </span>
      </div>

      {/* Hook */}
      <Field
        icon={<Sparkles className="h-3 w-3" />}
        label="Hook"
        body={idea.hook}
      />

      {/* Why now */}
      <Field
        icon={<TrendingUp className="h-3 w-3" />}
        label="Why now"
        body={idea.why_now}
      />

      {/* Rationale (small print) */}
      {idea.rationale && (
        <Field
          icon={<AlertCircle className="h-3 w-3" />}
          label="Confidence rationale"
          body={idea.rationale}
          dim
        />
      )}

      {/* Citations — comma-separated chips */}
      {idea.citations && idea.citations.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {idea.citations.map((c, i) => (
            <span
              key={i}
              className="rounded-md border border-border bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground"
            >
              {c}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Field({
  icon,
  label,
  body,
  dim = false,
}: {
  icon: React.ReactNode;
  label: string;
  body: string;
  dim?: boolean;
}) {
  return (
    <div className="ml-8 mt-1.5 flex gap-2 text-xs">
      <div
        className={cn(
          "mt-0.5 shrink-0",
          dim ? "text-muted-foreground/60" : "text-muted-foreground"
        )}
      >
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <span
          className={cn(
            "mr-1 font-medium",
            dim ? "text-muted-foreground/70" : "text-muted-foreground"
          )}
        >
          {label}:
        </span>
        <span className={dim ? "text-muted-foreground" : "text-foreground"}>
          {body}
        </span>
      </div>
    </div>
  );
}
