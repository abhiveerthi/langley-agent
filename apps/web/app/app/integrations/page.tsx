"use client";

import { useState } from "react";
import { CheckCircle, RefreshCw, Plus } from "lucide-react";
import { integrations } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const categories = ["All", "Storage", "Communication", "Production", "Platform", "Finance", "Productivity"];

const iconColors: Record<string, string> = {
  dropbox: "bg-blue-500/20 text-blue-400",
  drive: "bg-emerald-500/20 text-emerald-400",
  gmail: "bg-red-500/20 text-red-400",
  youtube: "bg-red-600/20 text-red-500",
  notion: "bg-zinc-500/20 text-zinc-300",
  slack: "bg-violet-500/20 text-violet-400",
  frameio: "bg-blue-600/20 text-blue-300",
  stripe: "bg-indigo-500/20 text-indigo-400",
};

const iconInitials: Record<string, string> = {
  dropbox: "Db",
  drive: "GD",
  gmail: "Gm",
  youtube: "YT",
  notion: "No",
  slack: "Sl",
  frameio: "Fr",
  stripe: "St",
};

const categoryColors: Record<string, string> = {
  Storage: "bg-blue-500/15 text-blue-400",
  Communication: "bg-violet-500/15 text-violet-400",
  Production: "bg-pink-500/15 text-pink-400",
  Platform: "bg-red-500/15 text-red-400",
  Finance: "bg-emerald-500/15 text-emerald-400",
  Productivity: "bg-amber-500/15 text-amber-400",
};

export default function IntegrationsPage() {
  const [activeCategory, setActiveCategory] = useState("All");
  const [requestText, setRequestText] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const filtered =
    activeCategory === "All"
      ? integrations
      : integrations.filter((i) => i.category === activeCategory);

  function handleRequest() {
    if (requestText.trim()) {
      setSubmitted(true);
      setTimeout(() => {
        setSubmitted(false);
        setRequestText("");
      }, 2000);
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Integrations</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect your tools to supercharge your workflow
        </p>
      </div>

      {/* Stats */}
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2 text-sm">
          <div className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-foreground font-medium">4 connected</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <div className="h-2 w-2 rounded-full bg-muted-foreground/40" />
          <span className="text-muted-foreground">4 available</span>
        </div>
      </div>

      {/* Category filter tabs */}
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={cn(
              "shrink-0 rounded-full px-4 py-1.5 text-xs font-medium transition-colors",
              activeCategory === cat
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:border-border/80 hover:text-foreground"
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Integration cards grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((integration) => (
          <div
            key={integration.id}
            className={cn(
              "rounded-lg border bg-card p-5 transition-colors",
              integration.connected ? "border-border" : "border-border hover:border-border/80"
            )}
          >
            <div className="mb-4 flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div
                  className={cn(
                    "flex h-10 w-10 items-center justify-center rounded-lg text-sm font-bold",
                    iconColors[integration.icon] ?? "bg-muted text-muted-foreground"
                  )}
                >
                  {iconInitials[integration.icon] ?? integration.name[0]}
                </div>
                <div>
                  <p className="font-medium text-foreground">{integration.name}</p>
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      categoryColors[integration.category] ?? "bg-muted text-muted-foreground"
                    )}
                  >
                    {integration.category}
                  </span>
                </div>
              </div>
              {integration.connected && (
                <div className="flex items-center gap-1 text-xs text-emerald-400">
                  <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Live
                </div>
              )}
            </div>

            <p className="mb-4 text-sm text-muted-foreground">{integration.description}</p>

            {integration.connected ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <CheckCircle className="h-3.5 w-3.5 text-emerald-400" />
                  <span>Connected &middot; Synced {integration.lastSync}</span>
                </div>
                <div className="flex gap-2">
                  <button className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-border py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
                    <RefreshCw className="h-3 w-3" />
                    Sync Now
                  </button>
                  <button className="flex-1 rounded-md border border-red-500/30 py-1.5 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/10">
                    Disconnect
                  </button>
                </div>
              </div>
            ) : (
              <button className="w-full rounded-md bg-primary py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90">
                Connect
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Request integration */}
      <div className="rounded-lg border border-border bg-card p-5">
        <h3 className="mb-1 text-sm font-semibold text-foreground">Request an Integration</h3>
        <p className="mb-3 text-xs text-muted-foreground">
          Don't see your tool? Let us know and we'll prioritize it.
        </p>
        <div className="flex gap-3">
          <input
            value={requestText}
            onChange={(e) => setRequestText(e.target.value)}
            placeholder="e.g. Zapier, Airtable, Final Cut Pro..."
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none"
            onKeyDown={(e) => e.key === "Enter" && handleRequest()}
          />
          <button
            onClick={handleRequest}
            className={cn(
              "flex shrink-0 items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors",
              submitted
                ? "bg-emerald-500 text-white"
                : "bg-primary text-primary-foreground hover:bg-primary/90"
            )}
          >
            <Plus className="h-4 w-4" />
            {submitted ? "Submitted!" : "Request"}
          </button>
        </div>
      </div>
    </div>
  );
}
