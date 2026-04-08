"use client";

import { useState } from "react";
import { Check, Edit2, RefreshCw, Sparkles } from "lucide-react";
import { thumbnailVariants } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const thumbnailGradients = [
  "bg-linear-to-br from-violet-600 via-indigo-700 to-indigo-900",
  "bg-linear-to-br from-zinc-700 via-zinc-800 to-zinc-900",
  "bg-linear-to-br from-orange-500 via-red-600 to-red-800",
  "bg-linear-to-br from-emerald-500 via-teal-600 to-cyan-800",
];

const colorPalettes = [
  "bg-indigo-500",
  "bg-violet-500",
  "bg-amber-500",
  "bg-emerald-500",
  "bg-red-500",
  "bg-pink-500",
  "bg-white",
  "bg-zinc-900",
];

const aiInsights = [
  "High contrast backgrounds work 34% better for your audience",
  "Add a face in the left 40% of frame — increases CTR by ~18%",
  "Bold sans-serif outperforms script fonts in your niche",
];

export default function ThumbnailsPage() {
  const [selected, setSelected] = useState("1");
  const [titleText, setTitleText] = useState("I Used AI to Build a $10K YouTube Channel");
  const [analyzing, setAnalyzing] = useState(false);

  function handleAnalyze() {
    setAnalyzing(true);
    setTimeout(() => setAnalyzing(false), 2000);
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Thumbnail Generator</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          AI-generated thumbnails that maximize click-through rate
        </p>
      </div>

      {/* Top row — video selector + analyze */}
      <div className="flex items-center gap-3">
        <select className="rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none">
          <option>10 AI Tools That Changed My Workflow Forever</option>
          <option>The Truth About Passive Income on YouTube</option>
          <option>Building a $10K/Month Creator Business</option>
        </select>
        <button
          onClick={handleAnalyze}
          className="flex shrink-0 items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          {analyzing ? (
            <>
              <RefreshCw className="h-4 w-4 animate-spin" />
              Extracting keyframes…
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4" />
              Analyze Video
            </>
          )}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Thumbnail variants */}
        <div className="lg:col-span-2">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Generated Variants
          </p>
          <div className="grid grid-cols-2 gap-4">
            {thumbnailVariants.map((variant, i) => (
              <div
                key={variant.id}
                className={cn(
                  "rounded-lg border-2 overflow-hidden bg-card transition-all",
                  selected === variant.id ? "border-primary shadow-lg shadow-primary/15" : "border-border"
                )}
              >
                {/* Thumbnail image placeholder */}
                <div className={cn("relative h-40", thumbnailGradients[i])}>
                  {/* Simulated thumbnail content */}
                  <div className="absolute inset-0 flex flex-col items-start justify-end p-4">
                    <div className="rounded bg-black/40 px-2 py-1 text-xs font-bold text-white uppercase tracking-wider">
                      {variant.style.replace("-", " ")}
                    </div>
                  </div>
                  {selected === variant.id && (
                    <div className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-full bg-primary">
                      <Check className="h-3.5 w-3.5 text-white" />
                    </div>
                  )}
                </div>
                <div className="p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-semibold text-foreground">{variant.label}</span>
                    <span className="text-xs text-muted-foreground">CTR {variant.ctrScore}%</span>
                  </div>
                  {/* CTR bar */}
                  <div className="mb-3 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${(variant.ctrScore / 10) * 100}%` }}
                    />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setSelected(variant.id)}
                      className={cn(
                        "flex flex-1 items-center justify-center gap-1 rounded-md py-1.5 text-xs font-medium transition-colors",
                        selected === variant.id
                          ? "bg-primary text-primary-foreground"
                          : "border border-border text-muted-foreground hover:text-foreground hover:bg-accent"
                      )}
                    >
                      <Check className="h-3 w-3" />
                      {selected === variant.id ? "Selected" : "Select"}
                    </button>
                    <button className="flex items-center justify-center gap-1 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
                      <Edit2 className="h-3 w-3" />
                      Edit
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right panel */}
        <div className="space-y-5">
          {/* AI Recommendations */}
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-3 flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                AI Recommendations
              </p>
            </div>
            <ul className="space-y-2.5">
              {aiInsights.map((insight, i) => (
                <li key={i} className="flex gap-2 text-xs text-foreground leading-snug">
                  <span className="mt-0.5 h-4 w-4 shrink-0 rounded-full bg-primary/20 flex items-center justify-center text-primary font-semibold text-[10px]">
                    {i + 1}
                  </span>
                  {insight}
                </li>
              ))}
            </ul>
          </div>

          {/* Title Text */}
          <div>
            <label className="mb-2 block text-xs font-medium text-foreground">Title Text</label>
            <textarea
              value={titleText}
              onChange={(e) => setTitleText(e.target.value)}
              rows={3}
              className="w-full resize-none rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none"
            />
          </div>

          {/* Color palette */}
          <div>
            <p className="mb-2 text-xs font-medium text-foreground">Color Palette</p>
            <div className="flex flex-wrap gap-2">
              {colorPalettes.map((color, i) => (
                <button
                  key={i}
                  className={cn(
                    "h-7 w-7 rounded-full border-2 transition-all hover:scale-110",
                    color,
                    i === 0 ? "border-primary" : "border-transparent"
                  )}
                />
              ))}
            </div>
          </div>

          {/* Regenerate */}
          <button className="flex w-full items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
            <RefreshCw className="h-4 w-4" />
            Regenerate Variants
          </button>
        </div>
      </div>
    </div>
  );
}
