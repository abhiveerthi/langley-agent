"use client";

import { useState } from "react";
import { Check, RefreshCw, ChevronDown } from "lucide-react";
import { dubbingLanguages } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const dubbingQueue = [
  { title: "10 AI Tools That Changed My Workflow Forever", lang: "Spanish", progress: 67, eta: "~3 min" },
  { title: "The Truth About Passive Income on YouTube", lang: "Portuguese", progress: 31, eta: "~8 min" },
];

const waveformBars = [20, 45, 30, 70, 55, 80, 40, 65, 50, 90, 35, 75, 60, 85, 45, 70, 30, 60, 50, 80, 40, 65, 55, 75, 35];

function statusStyle(status: string) {
  if (status === "ready") return "bg-emerald-500/15 text-emerald-400";
  if (status === "beta") return "bg-amber-500/15 text-amber-400";
  return "bg-zinc-500/15 text-zinc-400";
}

export default function DubbingPage() {
  const [selectedLang, setSelectedLang] = useState<string | null>("es");
  const [voiceBlend, setVoiceBlend] = useState(72);
  const [speechRate, setSpeechRate] = useState(1.0);
  const [autoPublish, setAutoPublish] = useState(false);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Voice Dubbing</h1>
        <p className="mt-1 text-sm text-muted-foreground">Clone your voice into any language</p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {/* Voice model card */}
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <p className="font-medium text-foreground">Sean's Voice Model</p>
                <div className="mt-1 flex items-center gap-1.5">
                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="text-xs text-emerald-400 font-medium">Trained — 47 min of data</span>
                </div>
              </div>
              <button className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-border/80 hover:text-foreground">
                <RefreshCw className="h-3.5 w-3.5" />
                Re-train
              </button>
            </div>
            {/* Waveform visualization */}
            <div className="flex items-center gap-0.5">
              {waveformBars.map((h, i) => (
                <div
                  key={i}
                  className="flex-1 rounded-sm bg-primary/60"
                  style={{ height: `${h * 0.5 + 8}px` }}
                />
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
              <span>Voice similarity: 96%</span>
              <span>Accent retention: 94%</span>
              <span>Emotion range: High</span>
            </div>
          </div>

          {/* Language grid */}
          <div>
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Target Languages
            </p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {dubbingLanguages.map((lang) => (
                <button
                  key={lang.code}
                  onClick={() => setSelectedLang(lang.code === selectedLang ? null : lang.code)}
                  className={cn(
                    "rounded-lg border p-4 text-left transition-all",
                    selectedLang === lang.code
                      ? "border-primary bg-primary/10 shadow-sm shadow-primary/10"
                      : "border-border bg-card hover:border-border/80 hover:bg-accent"
                  )}
                >
                  <div className="text-3xl">{lang.flag}</div>
                  <div className="mt-2 font-medium text-sm text-foreground">{lang.name}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{lang.subscribers} speakers</div>
                  <div className="mt-2">
                    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium capitalize", statusStyle(lang.status))}>
                      {lang.status}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Dubbing queue */}
          <div>
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Dubbing Queue
            </p>
            <div className="space-y-3">
              {dubbingQueue.map((item, i) => (
                <div key={i} className="rounded-lg border border-border bg-card p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-foreground line-clamp-1">{item.title}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">Dubbing to {item.lang} &middot; ETA {item.eta}</p>
                    </div>
                    <span className="ml-3 shrink-0 text-sm font-semibold text-primary">{item.progress}%</span>
                  </div>
                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Settings panel */}
        <div>
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Settings
          </p>
          <div className="rounded-lg border border-border bg-card p-4 space-y-5">
            {/* Voice blend */}
            <div>
              <div className="mb-2 flex justify-between">
                <label className="text-xs font-medium text-foreground">Voice Blend</label>
                <span className="text-xs text-muted-foreground">{voiceBlend}% original</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={voiceBlend}
                onChange={(e) => setVoiceBlend(Number(e.target.value))}
                className="w-full accent-primary"
              />
              <div className="mt-1 flex justify-between text-xs text-muted-foreground">
                <span>AI voice</span>
                <span>Your voice</span>
              </div>
            </div>

            {/* Speech rate */}
            <div>
              <div className="mb-2 flex justify-between">
                <label className="text-xs font-medium text-foreground">Speech Rate</label>
                <span className="text-xs text-muted-foreground">{speechRate.toFixed(1)}x</span>
              </div>
              <input
                type="range"
                min={0.5}
                max={2.0}
                step={0.1}
                value={speechRate}
                onChange={(e) => setSpeechRate(Number(e.target.value))}
                className="w-full accent-primary"
              />
              <div className="mt-1 flex justify-between text-xs text-muted-foreground">
                <span>0.5x</span>
                <span>2.0x</span>
              </div>
            </div>

            {/* Target language selector */}
            <div>
              <label className="mb-2 block text-xs font-medium text-foreground">Lip Sync Mode</label>
              <div className="relative">
                <select className="w-full appearance-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none">
                  <option>Auto (Recommended)</option>
                  <option>Precision Mode</option>
                  <option>Speed Mode</option>
                </select>
                <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              </div>
            </div>

            {/* Auto-publish toggle */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-foreground">Auto-publish</p>
                <p className="text-xs text-muted-foreground">Publish when dubbing completes</p>
              </div>
              <button
                onClick={() => setAutoPublish(!autoPublish)}
                className={cn(
                  "relative h-5 w-9 rounded-full transition-colors",
                  autoPublish ? "bg-primary" : "bg-muted"
                )}
              >
                <span
                  className={cn(
                    "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
                    autoPublish ? "left-5" : "left-0.5"
                  )}
                />
              </button>
            </div>

            <button className="w-full rounded-md bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
              Start Dubbing
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
