"use client";

import { useState } from "react";
import { Play, ChevronDown, Download } from "lucide-react";
import { cn } from "@/lib/utils";

const stylePresets = [
  {
    id: "reels-pop",
    label: "Reels Pop",
    preview: "Hey there!",
    style: "font-black text-yellow-400 drop-shadow-lg",
    bg: "bg-black",
  },
  {
    id: "clean-minimal",
    label: "Clean Minimal",
    preview: "Hey there!",
    style: "font-medium text-white",
    bg: "bg-zinc-900",
  },
  {
    id: "bold-impact",
    label: "Bold Impact",
    preview: "Hey there!",
    style: "font-extrabold text-white uppercase tracking-wider",
    bg: "bg-gray-900",
  },
  {
    id: "youtube-standard",
    label: "YouTube Standard",
    preview: "Hey there!",
    style: "font-normal text-white bg-black/70 px-2 py-0.5 rounded",
    bg: "bg-zinc-800",
  },
];

const subtitleBlocks = [
  { start: 5, width: 60, label: "Hey everyone, welcome back to the channel.", color: "bg-primary" },
  { start: 70, width: 50, label: "Today we're talking about AI tools.", color: "bg-violet-500" },
  { start: 130, width: 80, label: "And specifically how they changed my entire workflow.", color: "bg-primary" },
];

const exportFormats = ["SRT", "VTT", "ASS", "Burn-in"];

export default function SubtitlesPage() {
  const [selectedStyle, setSelectedStyle] = useState("reels-pop");
  const [speakerDiarization, setSpeakerDiarization] = useState(true);
  const [wordHighlighting, setWordHighlighting] = useState(true);
  const [scrubberPos, setScrubberPos] = useState(25);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Smart Subtitles</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Auto-generated, styled captions for every platform
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* Video preview (60%) */}
        <div className="space-y-4 lg:col-span-3">
          {/* Video area */}
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="relative flex h-64 items-center justify-center bg-zinc-900">
              <div className="absolute inset-0 bg-linear-to-br from-zinc-800 to-zinc-950" />
              <button className="relative flex h-14 w-14 items-center justify-center rounded-full bg-white/10 backdrop-blur-sm transition-colors hover:bg-white/20">
                <Play className="h-7 w-7 fill-white text-white ml-1" />
              </button>
              {/* Subtitle overlay */}
              <div className="absolute bottom-4 left-1/2 -translate-x-1/2">
                <span
                  className={cn(
                    "text-sm",
                    stylePresets.find((s) => s.id === selectedStyle)?.style
                  )}
                >
                  And specifically how they changed
                </span>
              </div>
              {/* Time */}
              <div className="absolute right-3 bottom-3 text-xs text-white/60">0:14 / 18:24</div>
            </div>

            {/* Timeline scrubber */}
            <div className="p-3">
              <input
                type="range"
                min={0}
                max={100}
                value={scrubberPos}
                onChange={(e) => setScrubberPos(Number(e.target.value))}
                className="w-full accent-primary"
              />
              <div className="mt-2 flex justify-between text-xs text-muted-foreground">
                <span>0:00</span>
                <span>18:24</span>
              </div>
            </div>
          </div>

          {/* Subtitle track visualization */}
          <div className="rounded-lg border border-border bg-card p-4">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Subtitle Track
            </p>
            <div className="relative h-10 rounded-md bg-muted overflow-hidden">
              {subtitleBlocks.map((block, i) => (
                <div
                  key={i}
                  title={block.label}
                  className={cn("absolute top-1 h-8 rounded cursor-pointer opacity-80 hover:opacity-100 transition-opacity flex items-center px-2", block.color)}
                  style={{ left: `${block.start}%`, width: `${block.width * 0.4}%` }}
                >
                  <span className="truncate text-xs text-white font-medium hidden sm:block">{block.label.split(" ").slice(0, 3).join(" ")}…</span>
                </div>
              ))}
              {/* Playhead */}
              <div
                className="absolute top-0 bottom-0 w-0.5 bg-white"
                style={{ left: `${scrubberPos}%` }}
              />
            </div>
            <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-primary" /> English
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-sm bg-violet-500" /> Speaker 2
              </span>
            </div>
          </div>
        </div>

        {/* Right panel (40%) */}
        <div className="space-y-5 lg:col-span-2">
          {/* Style presets */}
          <div>
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Style Preset
            </p>
            <div className="grid grid-cols-2 gap-2">
              {stylePresets.map((preset) => (
                <button
                  key={preset.id}
                  onClick={() => setSelectedStyle(preset.id)}
                  className={cn(
                    "rounded-lg border p-3 text-left transition-all",
                    selectedStyle === preset.id
                      ? "border-primary bg-primary/10"
                      : "border-border bg-card hover:border-border/80"
                  )}
                >
                  <div className={cn("mb-2 flex h-12 items-center justify-center rounded-md text-sm", preset.bg)}>
                    <span className={preset.style}>{preset.preview}</span>
                  </div>
                  <p className="text-xs font-medium text-foreground">{preset.label}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Language */}
          <div>
            <label className="mb-2 block text-xs font-medium text-foreground">Language</label>
            <div className="relative">
              <select className="w-full appearance-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none">
                <option>English (Auto-detected)</option>
                <option>Spanish</option>
                <option>Portuguese</option>
                <option>French</option>
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>

          {/* Toggles */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-foreground">Speaker Diarization</p>
                <p className="text-xs text-muted-foreground">Color-code multiple speakers</p>
              </div>
              <button
                onClick={() => setSpeakerDiarization(!speakerDiarization)}
                className={cn(
                  "relative h-5 w-9 rounded-full transition-colors",
                  speakerDiarization ? "bg-primary" : "bg-muted"
                )}
              >
                <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform", speakerDiarization ? "left-5" : "left-0.5")} />
              </button>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-foreground">Word Highlighting</p>
                <p className="text-xs text-muted-foreground">Highlight active word</p>
              </div>
              <button
                onClick={() => setWordHighlighting(!wordHighlighting)}
                className={cn(
                  "relative h-5 w-9 rounded-full transition-colors",
                  wordHighlighting ? "bg-primary" : "bg-muted"
                )}
              >
                <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform", wordHighlighting ? "left-5" : "left-0.5")} />
              </button>
            </div>
          </div>

          {/* Export */}
          <div>
            <p className="mb-2 text-xs font-medium text-foreground">Export Format</p>
            <div className="grid grid-cols-2 gap-2">
              {exportFormats.map((fmt) => (
                <button
                  key={fmt}
                  className="flex items-center justify-center gap-1.5 rounded-md border border-border py-2 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                >
                  <Download className="h-3 w-3" />
                  {fmt}
                </button>
              ))}
            </div>
          </div>

          <button className="w-full rounded-md bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
            Generate Subtitles
          </button>
        </div>
      </div>
    </div>
  );
}
