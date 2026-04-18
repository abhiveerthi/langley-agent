"use client";

import { useState } from "react";
import { Check, Play, Download, ExternalLink } from "lucide-react";
import { generatedClips } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const recentVideos = [
  { id: "1", title: "10 AI Tools That Changed My Workflow Forever", duration: "18:24", gradient: "bg-linear-to-br from-violet-600 to-indigo-800" },
  { id: "2", title: "The Truth About Passive Income on YouTube", duration: "14:33", gradient: "bg-linear-to-br from-emerald-600 to-teal-800" },
  { id: "3", title: "Building a $10K/Month Creator Business", duration: "31:05", gradient: "bg-linear-to-br from-orange-500 to-red-700" },
];

const pipelineSteps = [
  { label: "Upload", state: "complete" },
  { label: "Analyze", state: "complete" },
  { label: "Detect Moments", state: "complete" },
  { label: "Generate Clips", state: "active" },
  { label: "Export", state: "pending" },
];

const platformColors: Record<string, string> = {
  shorts: "bg-red-500/15 text-red-400",
  reels: "bg-pink-500/15 text-pink-400",
  tiktok: "bg-cyan-500/15 text-cyan-400",
};

const platformLabels: Record<string, string> = {
  shorts: "Shorts",
  reels: "Reels",
  tiktok: "TikTok",
};

function scoreColor(score: number) {
  if (score >= 90) return "bg-emerald-500/15 text-emerald-400";
  if (score >= 80) return "bg-amber-500/15 text-amber-400";
  return "bg-zinc-500/15 text-zinc-400";
}

const exportFormats = ["MP4 1080p", "MP4 720p", "MP4 480p", "WebM"];

const platformToggles = [
  { label: "YouTube Shorts", active: true },
  { label: "Instagram Reels", active: true },
  { label: "TikTok", active: false },
];

export default function ClipsPage() {
  const [selectedVideo, setSelectedVideo] = useState("1");
  const [selectedFormat, setSelectedFormat] = useState("MP4 1080p");
  const [toggles, setToggles] = useState(platformToggles);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Auto Clips</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Automatically extract viral moments for YouTube Shorts
        </p>
      </div>

      {/* Video selector */}
      <div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Select Video
        </p>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {recentVideos.map((video) => (
            <button
              key={video.id}
              onClick={() => setSelectedVideo(video.id)}
              className={cn(
                "flex shrink-0 flex-col overflow-hidden rounded-lg border transition-all",
                selectedVideo === video.id
                  ? "border-primary shadow-lg shadow-primary/10"
                  : "border-border hover:border-border/80"
              )}
              style={{ width: 180 }}
            >
              <div className={cn("h-24 relative", video.gradient)}>
                {selectedVideo === video.id && (
                  <div className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary">
                    <Check className="h-3 w-3 text-primary-foreground" />
                  </div>
                )}
                <div className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 text-xs text-white">
                  {video.duration}
                </div>
              </div>
              <div className="bg-card p-2.5">
                <p className="line-clamp-2 text-left text-xs font-medium leading-snug text-foreground">
                  {video.title}
                </p>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Pipeline steps */}
      <div className="rounded-lg border border-border bg-card p-5">
        <p className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Processing Pipeline
        </p>
        <div className="flex items-center">
          {pipelineSteps.map((step, i) => (
            <div key={step.label} className="flex flex-1 items-center">
              <div className="flex flex-col items-center gap-1.5">
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full border-2 text-xs font-semibold transition-all",
                    step.state === "complete"
                      ? "border-primary bg-primary text-primary-foreground"
                      : step.state === "active"
                      ? "border-primary bg-primary/20 text-primary animate-pulse"
                      : "border-border bg-muted text-muted-foreground"
                  )}
                >
                  {step.state === "complete" ? <Check className="h-4 w-4" /> : i + 1}
                </div>
                <span
                  className={cn(
                    "whitespace-nowrap text-xs",
                    step.state === "complete"
                      ? "text-primary font-medium"
                      : step.state === "active"
                      ? "text-foreground font-medium"
                      : "text-muted-foreground"
                  )}
                >
                  {step.label}
                </span>
              </div>
              {i < pipelineSteps.length - 1 && (
                <div
                  className={cn(
                    "mx-2 h-0.5 flex-1",
                    i < 2 ? "bg-primary" : "bg-border"
                  )}
                />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Generated clips */}
        <div className="lg:col-span-2">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Generated Clips
          </p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {generatedClips.map((clip, i) => {
              const clipGradients = [
                "bg-linear-to-br from-violet-600 to-indigo-800",
                "bg-linear-to-br from-pink-600 to-purple-800",
                "bg-linear-to-br from-emerald-600 to-teal-800",
                "bg-linear-to-br from-orange-500 to-red-700",
              ];
              return (
                <div key={clip.id} className="rounded-lg border border-border bg-card overflow-hidden">
                  <div className={cn("h-32 relative flex items-center justify-center", clipGradients[i])}>
                    <button className="flex h-10 w-10 items-center justify-center rounded-full bg-white/20 backdrop-blur-sm transition-colors hover:bg-white/30">
                      <Play className="h-5 w-5 fill-white text-white" />
                    </button>
                    <div className="absolute bottom-2 left-2 rounded bg-black/70 px-1.5 py-0.5 text-xs text-white">
                      {clip.duration}
                    </div>
                    <div className="absolute right-2 top-2">
                      <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", scoreColor(clip.score))}>
                        {clip.score}
                      </span>
                    </div>
                  </div>
                  <div className="p-3">
                    <p className="text-sm font-medium text-foreground">{clip.title}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {clip.platform.map((p) => (
                        <span key={p} className={cn("rounded-full px-2 py-0.5 text-xs font-medium", platformColors[p])}>
                          {platformLabels[p]}
                        </span>
                      ))}
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-border py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent">
                        <Play className="h-3 w-3" />
                        Preview
                      </button>
                      <button className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-primary py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90">
                        <Download className="h-3 w-3" />
                        Export
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Export options */}
        <div>
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Export Options
          </p>
          <div className="rounded-lg border border-border bg-card p-4 space-y-5">
            <div>
              <p className="mb-2 text-xs font-medium text-foreground">Platforms</p>
              <div className="space-y-2">
                {toggles.map((toggle, i) => (
                  <div key={toggle.label} className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">{toggle.label}</span>
                    <button
                      onClick={() =>
                        setToggles((prev) =>
                          prev.map((t, j) => (j === i ? { ...t, active: !t.active } : t))
                        )
                      }
                      className={cn(
                        "relative h-5 w-9 rounded-full transition-colors",
                        toggle.active ? "bg-primary" : "bg-muted"
                      )}
                    >
                      <span
                        className={cn(
                          "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
                          toggle.active ? "left-5" : "left-0.5"
                        )}
                      />
                    </button>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <p className="mb-2 text-xs font-medium text-foreground">Format</p>
              <div className="grid grid-cols-2 gap-2">
                {exportFormats.map((fmt) => (
                  <button
                    key={fmt}
                    onClick={() => setSelectedFormat(fmt)}
                    className={cn(
                      "rounded-md border py-1.5 text-xs font-medium transition-colors",
                      selectedFormat === fmt
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-border/80 hover:text-foreground"
                    )}
                  >
                    {fmt}
                  </button>
                ))}
              </div>
            </div>

            <button className="flex w-full items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
              <ExternalLink className="h-4 w-4" />
              Export All Clips
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
