"use client";

import { useState } from "react";
import { Copy, Maximize2, ChevronDown, ChevronRight, Wand2 } from "lucide-react";
import { cn } from "@/lib/utils";

const scriptContent = `Hey everyone, welcome back. Today we're going to break down something that completely changed how I approach content creation — and honestly, how I think about running a business online.

Over the past 18 months, AI tools have gone from novelty to necessity for serious creators. But not in the way most people talk about. It's not about replacing your creativity. It's about eliminating the work that was stealing your time.

Here's the thing nobody tells you: the average YouTuber spends 40% of their production time on tasks that could be automated. Writing titles. Researching keywords. Editing transcripts. Responding to comments. I was losing entire afternoons to this stuff.

So I ran an experiment. For 90 days, I integrated AI into every single part of my workflow. From ideation to publishing. And the results were — honestly — kind of wild.

My output went from 4 videos a month to 11. My average CTR improved from 4.2% to 7.8%. And the time I spent per video dropped from 22 hours to about 9. Same quality. Different process.

Today I'm going to walk you through exactly what I use, how I use it, and what actually works versus what's overhyped. Let's get into it.`;

const outlineSections = [
  { label: "Intro Hook", complete: true, sub: [] },
  { label: "Problem Statement", complete: true, sub: [] },
  {
    label: "Main Points", complete: false, sub: [
      "AI tools overview",
      "Workflow integration",
      "Real results breakdown",
    ]
  },
  { label: "Case Study", complete: false, sub: [] },
  { label: "CTA", complete: false, sub: [] },
];

const formats = ["Long-form", "Short-form", "Shorts Script"];
const tones = ["Conversational", "Educational", "Entertaining"];

function wordCount(text: string) {
  return text.trim().split(/\s+/).length;
}

function readingTime(words: number) {
  return Math.ceil(words / 150);
}

export default function ScriptsPage() {
  const [topic, setTopic] = useState(
    "How AI tools are changing the YouTube creator economy in 2025"
  );
  const [selectedFormat, setSelectedFormat] = useState("Long-form");
  const [selectedTone, setSelectedTone] = useState("Conversational");
  const [voiceMatch, setVoiceMatch] = useState(true);
  const [script, setScript] = useState(scriptContent);
  const [teleprompter, setTeleprompter] = useState(false);
  const [expandedSection, setExpandedSection] = useState<string | null>("Main Points");
  const [copied, setCopied] = useState(false);

  const words = wordCount(script);
  const minutes = readingTime(words);

  function handleCopy() {
    navigator.clipboard.writeText(script);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className={cn("flex h-full flex-col", teleprompter && "bg-black")}>
      {teleprompter ? (
        // Teleprompter mode
        <div className="flex flex-1 flex-col items-center overflow-y-auto px-16 py-12">
          <div className="mb-6 flex items-center gap-3">
            <button
              onClick={() => setTeleprompter(false)}
              className="rounded-md bg-white/10 px-4 py-1.5 text-sm text-white hover:bg-white/20"
            >
              Exit Teleprompter
            </button>
          </div>
          <p className="max-w-3xl text-center text-3xl font-medium leading-relaxed text-white">
            {script}
          </p>
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden p-6 gap-6">
          {/* Left controls */}
          <div className="flex w-72 shrink-0 flex-col gap-5">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-foreground">Script Writer</h1>
              <p className="mt-1 text-sm text-muted-foreground">AI-powered scripts in your voice</p>
            </div>

            <div>
              <label className="mb-2 block text-xs font-medium text-foreground">Topic</label>
              <textarea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                rows={3}
                className="w-full resize-none rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary/50 focus:outline-none"
              />
            </div>

            <div>
              <label className="mb-2 block text-xs font-medium text-foreground">Format</label>
              <div className="flex flex-col gap-1.5">
                {formats.map((fmt) => (
                  <button
                    key={fmt}
                    onClick={() => setSelectedFormat(fmt)}
                    className={cn(
                      "rounded-md border px-3 py-2 text-left text-sm transition-colors",
                      selectedFormat === fmt
                        ? "border-primary bg-primary/10 text-primary font-medium"
                        : "border-border text-muted-foreground hover:border-border/80 hover:text-foreground"
                    )}
                  >
                    {fmt}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-2 block text-xs font-medium text-foreground">Tone</label>
              <div className="flex flex-col gap-1.5">
                {tones.map((tone) => (
                  <button
                    key={tone}
                    onClick={() => setSelectedTone(tone)}
                    className={cn(
                      "rounded-md border px-3 py-2 text-left text-sm transition-colors",
                      selectedTone === tone
                        ? "border-primary bg-primary/10 text-primary font-medium"
                        : "border-border text-muted-foreground hover:border-border/80 hover:text-foreground"
                    )}
                  >
                    {tone}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-foreground">Match my style</p>
                <p className="text-xs text-muted-foreground">Use your voice model</p>
              </div>
              <button
                onClick={() => setVoiceMatch(!voiceMatch)}
                className={cn(
                  "relative h-5 w-9 rounded-full transition-colors",
                  voiceMatch ? "bg-primary" : "bg-muted"
                )}
              >
                <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform", voiceMatch ? "left-5" : "left-0.5")} />
              </button>
            </div>

            <button className="flex items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
              <Wand2 className="h-4 w-4" />
              Generate Script
            </button>

            {/* Outline */}
            <div className="rounded-lg border border-border bg-card p-3">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Outline
              </p>
              <div className="space-y-1">
                {outlineSections.map((section) => (
                  <div key={section.label}>
                    <button
                      onClick={() =>
                        setExpandedSection(
                          expandedSection === section.label ? null : section.label
                        )
                      }
                      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
                    >
                      {section.sub.length > 0 ? (
                        expandedSection === section.label ? (
                          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                        )
                      ) : (
                        <span className="h-3 w-3 shrink-0" />
                      )}
                      <span className={cn("font-medium", section.complete ? "text-muted-foreground line-through" : "text-foreground")}>
                        {section.label}
                      </span>
                    </button>
                    {expandedSection === section.label && section.sub.length > 0 && (
                      <div className="ml-5 space-y-1 py-1">
                        {section.sub.map((sub) => (
                          <div key={sub} className="flex items-center gap-2 px-2 py-1 text-xs text-muted-foreground">
                            <span className="h-1 w-1 rounded-full bg-muted-foreground/50" />
                            {sub}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right script display */}
          <div className="flex flex-1 flex-col overflow-hidden rounded-lg border border-border bg-card">
            {/* Toolbar */}
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                <span><span className="font-medium text-foreground">{words}</span> words</span>
                <span><span className="font-medium text-foreground">~{minutes} min</span> read</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setTeleprompter(true)}
                  className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-border/80 hover:text-foreground"
                >
                  <Maximize2 className="h-3 w-3" />
                  Teleprompter
                </button>
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-border/80 hover:text-foreground"
                >
                  <Copy className="h-3 w-3" />
                  {copied ? "Copied!" : "Copy"}
                </button>
              </div>
            </div>
            {/* Script content */}
            <textarea
              value={script}
              onChange={(e) => setScript(e.target.value)}
              className="flex-1 resize-none bg-transparent px-6 py-5 text-sm leading-7 text-foreground focus:outline-none"
            />
          </div>
        </div>
      )}
    </div>
  );
}
