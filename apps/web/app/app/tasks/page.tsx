"use client";

import { useState } from "react";
import {
  Plus,
  Radar,
  Lightbulb,
  Languages,
  Scissors,
  Search,
  Image,
  Subtitles,
  Mail,
  FileText,
  Download,
  RefreshCw,
  AlertCircle,
  Clock,
  CheckCircle2,
} from "lucide-react";
import { tasks } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

type FilterTab = "all" | "running" | "queued" | "complete" | "failed";

const typeIcon: Record<string, React.ElementType> = {
  research: Radar,
  intel: Lightbulb,
  dubbing: Languages,
  clips: Scissors,
  seo: Search,
  thumbnails: Image,
  subtitles: Subtitles,
  comms: Mail,
};

const typeColor: Record<string, string> = {
  research: "bg-indigo-500/10 text-indigo-400",
  intel: "bg-violet-500/10 text-violet-400",
  dubbing: "bg-sky-500/10 text-sky-400",
  clips: "bg-orange-500/10 text-orange-400",
  seo: "bg-teal-500/10 text-teal-400",
  thumbnails: "bg-pink-500/10 text-pink-400",
  subtitles: "bg-amber-500/10 text-amber-400",
  comms: "bg-emerald-500/10 text-emerald-400",
};

function StatusBadge({ status }: { status: string }) {
  if (status === "complete") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-400">
        <CheckCircle2 className="h-3 w-3" />
        Complete
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
        <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
        Running
      </span>
    );
  }
  if (status === "queued") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-1 text-xs font-medium text-amber-400">
        <Clock className="h-3 w-3" />
        Queued
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1 text-xs font-medium text-red-400">
        <AlertCircle className="h-3 w-3" />
        Failed
      </span>
    );
  }
  return null;
}

const filterTabs: { key: FilterTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "running", label: "Running" },
  { key: "queued", label: "Queued" },
  { key: "complete", label: "Complete" },
  { key: "failed", label: "Failed" },
];

export default function TasksPage() {
  const [activeTab, setActiveTab] = useState<FilterTab>("all");

  const counts = {
    all: tasks.length,
    running: tasks.filter((t) => t.status === "running").length,
    queued: tasks.filter((t) => t.status === "queued").length,
    complete: tasks.filter((t) => t.status === "complete").length,
    failed: tasks.filter((t) => t.status === "failed").length,
  };

  const filtered =
    activeTab === "all" ? tasks : tasks.filter((t) => t.status === activeTab);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Tasks</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            All agent and studio work, in one place
          </p>
        </div>
        <button className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90">
          <Plus className="h-4 w-4" />
          Trigger Task
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Running", value: counts.running, color: "text-primary", bg: "bg-primary/10" },
          { label: "Queued", value: counts.queued, color: "text-amber-400", bg: "bg-amber-500/10" },
          { label: "Completed", value: counts.complete, color: "text-emerald-400", bg: "bg-emerald-500/10" },
          { label: "Failed", value: counts.failed, color: "text-red-400", bg: "bg-red-500/10" },
        ].map((stat) => (
          <div key={stat.label} className="rounded-lg border border-border bg-card p-4 flex items-center gap-3">
            <div className={cn("h-9 w-9 shrink-0 rounded-lg flex items-center justify-center text-base font-bold", stat.bg, stat.color)}>
              {stat.value}
            </div>
            <span className="text-sm text-muted-foreground">{stat.label}</span>
          </div>
        ))}
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1 border-b border-border">
        {filterTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              "relative flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px",
              activeTab === tab.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
            <span
              className={cn(
                "rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                activeTab === tab.key
                  ? "bg-primary/20 text-primary"
                  : "bg-muted text-muted-foreground"
              )}
            >
              {counts[tab.key]}
            </span>
          </button>
        ))}
      </div>

      {/* Task list */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="h-12 w-12 rounded-full bg-muted/40 flex items-center justify-center mb-3">
            <CheckCircle2 className="h-6 w-6 text-muted-foreground" />
          </div>
          <h3 className="text-sm font-medium text-foreground mb-1">No {activeTab} tasks</h3>
          <p className="text-xs text-muted-foreground">Tasks will appear here when they match this filter.</p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {filtered.map((task) => {
            const Icon = typeIcon[task.type] ?? FileText;
            const iconColor = typeColor[task.type] ?? "bg-muted text-muted-foreground";

            return (
              <div
                key={task.id}
                className="rounded-lg border border-border bg-card p-4 hover:bg-accent/20 transition-colors"
              >
                <div className="flex items-start gap-4">
                  {/* Icon */}
                  <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg mt-0.5", iconColor)}>
                    <Icon className="h-4 w-4" />
                  </div>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-1.5">
                      <span className="text-sm font-medium text-foreground leading-tight">{task.name}</span>
                      <StatusBadge status={task.status} />
                    </div>

                    <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
                      <span>
                        Triggered by: <span className="text-foreground/70">{task.triggeredBy}</span>
                      </span>
                      <span>
                        Created: <span className="text-foreground/70">{task.createdAt}</span>
                      </span>
                      {task.duration && (
                        <span>
                          Duration: <span className="text-foreground/70">{task.duration}</span>
                        </span>
                      )}
                    </div>

                    {/* Progress bar (running only) */}
                    {task.status === "running" && (
                      <div className="mt-2.5">
                        <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
                          <span>Progress</span>
                          <span>{task.progress}%</span>
                        </div>
                        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full rounded-full bg-primary transition-all"
                            style={{ width: `${task.progress}%` }}
                          />
                        </div>
                      </div>
                    )}

                    {/* Output pill */}
                    {task.status === "complete" && task.outputLabel && (
                      <div className="mt-2">
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/30 px-2.5 py-1 text-[11px] text-muted-foreground">
                          <FileText className="h-3 w-3" />
                          {task.outputLabel}
                        </span>
                      </div>
                    )}

                    {/* Failed reason */}
                    {task.status === "failed" && task.outputLabel && (
                      <div className="mt-2">
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-red-500/20 bg-red-500/10 px-2.5 py-1 text-[11px] text-red-400">
                          <AlertCircle className="h-3 w-3" />
                          {task.outputLabel}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 shrink-0">
                    {task.status === "complete" && task.output?.includes("PDF") && (
                      <button className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
                        <Download className="h-3 w-3" />
                        Download
                      </button>
                    )}
                    {task.status === "failed" && (
                      <button className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
                        <RefreshCw className="h-3 w-3" />
                        Retry
                      </button>
                    )}
                    {task.status === "running" && (
                      <button className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
                        <RefreshCw className="h-3 w-3 animate-spin" />
                        Running...
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
