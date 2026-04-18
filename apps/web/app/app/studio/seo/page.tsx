"use client";

import { useState } from "react";
import { Check, X, Plus } from "lucide-react";
import { seoTitles } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const initialTags = [
  "AI tools 2025", "YouTube growth", "content creation", "AI workflow",
  "YouTube algorithm", "creator economy", "video editing AI", "ChatGPT YouTube",
  "passive income YouTube", "YouTube monetization", "AI automation",
  "creator tools", "YouTube tips", "grow on YouTube", "AI content",
];

const descriptionText = `In this video, I break down the exact AI tools and workflow that helped me grow my YouTube channel from 0 to 847K subscribers in under 2 years.

🔥 What you'll learn:
• The 5 AI tools that actually move the needle for creators
• My complete video production workflow (ideation → publish)
• Real revenue numbers and how AI cut my production time in half

Whether you're just starting out or looking to scale your existing channel, this step-by-step breakdown gives you a replicable system.

📌 Timestamps:
0:00 - Intro
2:14 - Why AI changed everything for creators
6:30 - Tool #1: Script writing with AI
10:45 - Tool #2: Thumbnail generation
14:20 - Tool #3: SEO optimization
18:05 - Results and what to do next

🔔 Subscribe for weekly videos on AI, YouTube growth, and the creator economy.

#AItools #YouTubeGrowth #ContentCreation #CreatorEconomy #AI2025`;

const seoBreakdown = [
  { label: "Keyword Coverage", score: 91, color: "bg-emerald-500" },
  { label: "Click-through Potential", score: 88, color: "bg-primary" },
  { label: "Search Intent Match", score: 74, color: "bg-amber-500" },
  { label: "Competition Score", score: 64, color: "bg-red-400" },
];

function volumeColor(vol: string) {
  if (vol === "Very High") return "bg-emerald-500/15 text-emerald-400";
  if (vol === "High") return "bg-primary/15 text-primary";
  return "bg-zinc-500/15 text-zinc-400";
}

function scoreRingColor(score: number) {
  if (score >= 90) return "stroke-emerald-500";
  if (score >= 80) return "stroke-primary";
  if (score >= 70) return "stroke-amber-500";
  return "stroke-red-400";
}

export default function SeoPage() {
  const [selectedTitle, setSelectedTitle] = useState(0);
  const [description, setDescription] = useState(descriptionText);
  const [tags, setTags] = useState(initialTags);
  const [newTag, setNewTag] = useState("");
  const [hoveredTag, setHoveredTag] = useState<number | null>(null);

  const overallScore = 82;
  const circumference = 2 * Math.PI * 28;
  const dashOffset = circumference - (overallScore / 100) * circumference;

  function addTag() {
    if (newTag.trim() && !tags.includes(newTag.trim())) {
      setTags([...tags, newTag.trim()]);
      setNewTag("");
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">SEO Optimizer</h1>
        <p className="mt-1 text-sm text-muted-foreground">Maximize discoverability on YouTube search</p>
      </div>

      {/* Video selector */}
      <select className="rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none">
        <option>10 AI Tools That Changed My Workflow Forever</option>
        <option>The Truth About Passive Income on YouTube</option>
        <option>Building a $10K/Month Creator Business</option>
      </select>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Main sections */}
        <div className="space-y-6 lg:col-span-2">
          {/* Title suggestions */}
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="border-b border-border px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Title Suggestions
              </p>
            </div>
            <div className="divide-y divide-border">
              {seoTitles.map((item, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex items-center gap-4 px-4 py-3 transition-colors cursor-pointer",
                    selectedTitle === i ? "bg-primary/10" : "hover:bg-accent"
                  )}
                  onClick={() => setSelectedTitle(i)}
                >
                  {/* Score circle */}
                  <div
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                      item.score >= 90
                        ? "bg-emerald-500/15 text-emerald-400"
                        : item.score >= 80
                        ? "bg-primary/15 text-primary"
                        : "bg-amber-500/15 text-amber-400"
                    )}
                  >
                    {item.score}
                  </div>
                  <p className="flex-1 text-sm text-foreground">{item.title}</p>
                  <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-xs font-medium", volumeColor(item.searchVolume))}>
                    {item.searchVolume}
                  </span>
                  <button
                    onClick={(e) => { e.stopPropagation(); setSelectedTitle(i); }}
                    className={cn(
                      "shrink-0 rounded-md px-3 py-1 text-xs font-medium transition-colors",
                      selectedTitle === i
                        ? "bg-primary text-primary-foreground"
                        : "border border-border text-muted-foreground hover:text-foreground hover:bg-accent"
                    )}
                  >
                    {selectedTitle === i ? (
                      <span className="flex items-center gap-1"><Check className="h-3 w-3" /> Using</span>
                    ) : "Use This"}
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Description editor */}
          <div className="rounded-lg border border-border bg-card">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Description
              </p>
              <div className="flex gap-3 text-xs text-muted-foreground">
                <span><span className="font-medium text-foreground">14</span> keywords</span>
                <span>Readability: <span className="font-medium text-emerald-400">Good</span></span>
              </div>
            </div>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={10}
              className="w-full resize-none bg-transparent px-4 py-3 text-sm leading-relaxed text-foreground focus:outline-none"
            />
          </div>

          {/* Tags */}
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Tags
            </p>
            <div className="flex flex-wrap gap-2 mb-3">
              {tags.map((tag, i) => (
                <div
                  key={tag}
                  className="relative"
                  onMouseEnter={() => setHoveredTag(i)}
                  onMouseLeave={() => setHoveredTag(null)}
                >
                  <span className="flex items-center gap-1.5 rounded-full border border-border bg-muted px-3 py-1 text-xs text-foreground">
                    {tag}
                    <button
                      onClick={() => setTags(tags.filter((_, j) => j !== i))}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </span>
                  {hoveredTag === i && (
                    <div className="absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded bg-card border border-border px-2 py-1 text-xs text-muted-foreground shadow-lg z-10">
                      Vol: {Math.floor(Math.random() * 900 + 100)}K/mo
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addTag()}
                placeholder="Add tag…"
                className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none"
              />
              <button
                onClick={addTag}
                className="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground"
              >
                <Plus className="h-3 w-3" />
                Add
              </button>
            </div>
          </div>
        </div>

        {/* SEO score sidebar */}
        <div className="space-y-5">
          {/* Overall score */}
          <div className="rounded-lg border border-border bg-card p-5 text-center">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              SEO Score
            </p>
            <div className="flex items-center justify-center">
              <svg width="80" height="80" viewBox="0 0 80 80">
                <circle cx="40" cy="40" r="28" fill="none" stroke="currentColor" strokeWidth="6" className="text-muted" />
                <circle
                  cx="40"
                  cy="40"
                  r="28"
                  fill="none"
                  strokeWidth="6"
                  strokeLinecap="round"
                  strokeDasharray={circumference}
                  strokeDashoffset={dashOffset}
                  className={scoreRingColor(overallScore)}
                  transform="rotate(-90 40 40)"
                />
                <text x="40" y="45" textAnchor="middle" className="fill-foreground text-base font-bold" fontSize="18">
                  {overallScore}
                </text>
              </svg>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">out of 100</p>
            <div className="mt-3 rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
              Strong — Keep optimizing
            </div>
          </div>

          {/* Breakdown */}
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Score Breakdown
            </p>
            <div className="space-y-3">
              {seoBreakdown.map((item) => (
                <div key={item.label}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="text-muted-foreground">{item.label}</span>
                    <span className="font-medium text-foreground">{item.score}%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn("h-full rounded-full", item.color)}
                      style={{ width: `${item.score}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button className="w-full rounded-md bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
            Apply All Suggestions
          </button>
        </div>
      </div>
    </div>
  );
}
