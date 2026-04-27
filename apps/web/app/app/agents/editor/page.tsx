"use client";

import Link from "next/link";
import {
  ArrowLeft,
  Scissors,
  Sparkles,
  ShieldCheck,
  Wrench,
  Languages,
  Subtitles,
  Image as ImageIcon,
  Bell,
  Lock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { YouTubeStatusPill } from "@/components/integrations/YouTubeStatusPill";

// Coming-soon dashboard for the Editor agent. Same shape as the other agent
// pages so that when the video worker lands and tools come online, the only
// thing that changes is removing the disabled banner and lighting up the
// capability cards / tools list.
//
// Scope intentionally narrow: post-production media work only. Script writing
// belongs to Strategist (idea → outline) and SEO/metadata belongs to Publisher
// (kit → push). Putting them here would split the same job across two agents.

const capabilities: { title: string; body: string; icon: React.ElementType }[] = [
  {
    icon: Scissors,
    title: "Auto Clips",
    body: "Long-form upload → ready-to-post shorts. Detects high-energy moments, frames vertical, exports per-platform aspect ratios for Shorts / Reels / TikTok.",
  },
  {
    icon: Languages,
    title: "Dubbing",
    body: "Translate and voice-clone a video into target languages so one upload reaches multiple regions without re-recording.",
  },
  {
    icon: Subtitles,
    title: "Subtitles",
    body: "Generate burned-in captions or VTT sidecars. Punctuation-aware, speaker-labelled, ready to upload alongside the video.",
  },
  {
    icon: ImageIcon,
    title: "Thumbnails",
    body: "Pull faces and high-energy frames, render 3–5 thumbnail variants with overlay copy. The Publisher already drafts the copy — Editor renders the image.",
  },
];

const tools = [
  "extract_clips",
  "render_subtitles",
  "translate_audio",
  "generate_thumbnail",
  "export_video",
];

export default function EditorAgentPage() {
  return (
    <div className="flex h-full min-h-0">
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <div>
          <Link
            href="/app/agents"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3 transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Agents
          </Link>
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-zinc-500/10 border border-zinc-500/20">
              <Scissors className="h-5 w-5 text-zinc-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Editor</h1>
              <p className="text-sm text-muted-foreground">
                Cuts long-form video into shorts, dubs, captions, and thumbnails. Hands the rendered files back to Publisher to ship.
              </p>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-zinc-500/30 bg-zinc-500/10 px-3 py-1.5">
              <span className="h-2 w-2 rounded-full bg-zinc-400" />
              <span className="text-sm font-medium text-zinc-400">Coming soon</span>
            </div>
          </div>
        </div>

        {/* Coming-soon banner */}
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-amber-500/10 border border-amber-500/20">
              <Lock className="h-4 w-4 text-amber-400" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-foreground">Video worker not yet available</div>
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                Editor needs a media-processing worker that can pull video from YouTube, run ffmpeg / Whisper / image-gen pipelines, and push results back. The agent shell exists — what&apos;s missing is the worker behind the tools.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  disabled
                  className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/20 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-400 opacity-60 cursor-not-allowed"
                >
                  <Bell className="h-3 w-3" />
                  Notify me when it ships
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Stats — placeholders so the layout matches other agents */}
        <div className="grid grid-cols-3 gap-4">
          <Stat label="Clips rendered" value="—" />
          <Stat label="Languages dubbed" value="—" />
          <Stat label="Avg turnaround" value="—" />
        </div>

        {/* Capabilities */}
        <Section title="What the Editor will do" subtitle="Each capability is its own pipeline. You can ask for one without triggering the others — &quot;just give me the shorts&quot; or &quot;add Spanish subtitles to this one&quot;.">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {capabilities.map((c) => (
              <CapabilityCard key={c.title} {...c} disabled />
            ))}
          </div>
        </Section>

        {/* Approval flow */}
        <Section title="Approval flow" subtitle="Renders are reviewable before they land in Publisher. No auto-publish.">
          <div className="rounded-lg border border-border bg-card p-5 opacity-90">
            <div className="flex items-center gap-2 text-sm font-medium text-foreground mb-3">
              <ShieldCheck className="h-4 w-4 text-zinc-400" />
              Render and hand off
            </div>
            <ol className="space-y-2 text-sm text-muted-foreground">
              <li className="flex gap-2.5"><span className="text-zinc-400 font-mono">1.</span><span>You ask: <span className="text-foreground">&quot;cut shorts from my latest upload&quot;</span></span></li>
              <li className="flex gap-2.5"><span className="text-zinc-400 font-mono">2.</span><span>Editor runs the pipeline in the worker, returns 3–5 candidate clips with timestamps.</span></li>
              <li className="flex gap-2.5"><span className="text-zinc-400 font-mono">3.</span><span>You preview + pick the keepers. Rejected clips can be revised with a quick note.</span></li>
              <li className="flex gap-2.5"><span className="text-zinc-400 font-mono">4.</span><span>Approved files land on a Publisher package, ready to schedule across Shorts / Reels / TikTok.</span></li>
            </ol>
          </div>
        </Section>

        {/* Tools */}
        <Section title="Tools (planned)" subtitle="Names not final — these are the pipeline entry points the worker will expose.">
          <div className="flex flex-wrap gap-1.5">
            {tools.map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/30 px-2 py-1 text-[11px] font-mono text-muted-foreground/70"
              >
                <Wrench className="h-3 w-3 text-zinc-400" />
                {t}
              </span>
            ))}
          </div>
        </Section>

        {/* What's NOT here */}
        <Section title="What lives elsewhere" subtitle="To keep the lanes clean, two things you might expect here are owned by other agents.">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <ScopeNote
              title="Script & hook writing"
              owner="Strategist"
              href="/app/agents/strategist"
              body="Pre-production ideation is the Strategist's job — outlines, hook variants, ranked ideas. Editor only renders what already exists."
            />
            <ScopeNote
              title="Titles, descriptions, tags"
              owner="Publisher"
              href="/app/agents/publisher"
              body="Metadata kits ship from Publisher (title variants, description, tags, chapters, pinned comment). Editor hands the rendered media to a Publisher package."
            />
          </div>
        </Section>
      </div>

      {/* Right rail */}
      <div className="w-80 shrink-0 border-l border-border bg-card/50 overflow-y-auto p-5 space-y-6">
        <YouTubeStatusPill heading="Channel Connected" />

        <div className="rounded-lg border border-border bg-muted/20 p-4 text-xs text-muted-foreground space-y-2">
          <div className="flex items-center gap-2 text-foreground font-medium">
            <Sparkles className="h-3.5 w-3.5 text-zinc-400" />
            Until it ships
          </div>
          <p>
            For shorts in the meantime, render in your editor of choice and drop the clips into a Publisher package — Publisher will write the captions and schedule them.
          </p>
          <p>
            For thumbnails, ask Publisher for the overlay copy ideas; you can render the image yourself in the meantime.
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Subcomponents (kept local — same shape as other agent pages) ─────────

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-muted/10 p-4">
      <div className="text-2xl font-bold text-muted-foreground/60">{value}</div>
      <div className="text-xs text-muted-foreground mt-1">{label}</div>
    </div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {subtitle && <p className="text-xs text-muted-foreground mt-0.5 mb-3">{subtitle}</p>}
      {!subtitle && <div className="mb-3" />}
      {children}
    </div>
  );
}

function CapabilityCard({
  icon: Icon,
  title,
  body,
  disabled,
}: {
  icon: React.ElementType;
  title: string;
  body: string;
  disabled?: boolean;
}) {
  return (
    <div className={cn("rounded-lg border border-border bg-card p-4 flex gap-3", disabled && "opacity-75")}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-zinc-500/10 border border-zinc-500/20">
        <Icon className="h-4 w-4 text-zinc-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <div className="text-sm font-medium text-foreground">{title}</div>
          {disabled && (
            <span className="rounded-full border border-zinc-500/20 bg-zinc-500/10 px-1.5 py-0 text-[9px] font-medium text-zinc-400 uppercase tracking-wide">
              Soon
            </span>
          )}
        </div>
        <div className="text-xs text-muted-foreground mt-1 leading-relaxed">{body}</div>
      </div>
    </div>
  );
}

function ScopeNote({ title, owner, href, body }: { title: string; owner: string; href: string; body: string }) {
  return (
    <Link
      href={href}
      className="block rounded-lg border border-border bg-card p-4 hover:border-foreground/20 transition-colors"
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="text-sm font-medium text-foreground">{title}</div>
        <span className="text-[11px] font-medium text-muted-foreground shrink-0">→ {owner}</span>
      </div>
      <div className="text-xs text-muted-foreground leading-relaxed">{body}</div>
    </Link>
  );
}
