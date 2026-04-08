import Link from "next/link";
import {
  ArrowLeft,
  FileText,
  Download,
  Eye,
  Lightbulb,
  CalendarDays,
  Plus,
  CheckCircle2,
  TrendingUp,
  X,
} from "lucide-react";
import { brandBriefs } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const videoIdeas = [
  { title: "AI Editor Showdown: Which Tool Actually Saves More Time?", score: 94, tag: "High CTR" },
  { title: "I Gave 3 AI Tools My Worst Video — Here's What Happened", score: 88, tag: "Trending" },
  { title: "The Creator Burnout Formula (And How I Fixed It)", score: 82, tag: "Audience Demand" },
  { title: "Repurposing One Video Into 30 Pieces of Content", score: 77, tag: "Workflow" },
  { title: "My Full YouTube Shorts Strategy for Q2 2026", score: 71, tag: "Shorts" },
];

const competitors = ["TechWithTim", "MKBHD", "Ali Abdaal"];

const focusTopics = ["AI tools", "Creator workflow", "YouTube strategy", "Passive income", "Tech reviews"];

export default function IntelAgentPage() {
  return (
    <div className="flex h-full min-h-0">
      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <div>
          <Link
            href="/agents"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3 transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            All Agents
          </Link>
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-500/10 border border-violet-500/20">
              <Lightbulb className="h-5 w-5 text-violet-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Content Strategist</h1>
              <p className="text-sm text-muted-foreground">Analyzes channel performance and generates data-backed video ideas</p>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-sm font-medium text-emerald-400">Active</span>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "Brand Briefs", value: "23" },
            { label: "Video Ideas Generated", value: "89" },
            { label: "Avg CTR Lift", value: "+12%" },
          ].map((stat) => (
            <div key={stat.label} className="rounded-lg border border-border bg-card p-4">
              <div className="text-2xl font-bold text-foreground">{stat.value}</div>
              <div className="text-xs text-muted-foreground mt-1">{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Recent Brand Briefs */}
        <div>
          <h2 className="text-base font-semibold text-foreground mb-3">Recent Brand Briefs</h2>
          <div className="space-y-3">
            {brandBriefs.map((brief, i) => (
              <div key={i} className="rounded-lg border border-border bg-card p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-violet-500/10">
                      <FileText className="h-4 w-4 text-violet-400" />
                    </div>
                    <div>
                      <div className="font-medium text-foreground text-sm">{brief.title}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">{brief.date} · {brief.size}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
                      <Eye className="h-3.5 w-3.5" />
                      View
                    </button>
                    <button className="flex items-center gap-1.5 rounded-md bg-violet-500/10 border border-violet-500/20 px-3 py-1.5 text-xs font-medium text-violet-400 hover:bg-violet-500/20 transition-colors">
                      <Download className="h-3.5 w-3.5" />
                      Download PDF
                    </button>
                  </div>
                </div>
                <div className="mt-3 space-y-1.5 pl-12">
                  {brief.highlights.map((h, j) => (
                    <div key={j} className="flex items-start gap-2 text-xs text-muted-foreground">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-violet-400" />
                      {h}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Top Generated Ideas */}
        <div>
          <h2 className="text-base font-semibold text-foreground mb-3">Top Generated Ideas</h2>
          <div className="space-y-2.5">
            {videoIdeas.map((idea, i) => (
              <div
                key={i}
                className="flex items-center gap-4 rounded-lg border border-border bg-card px-4 py-3 hover:bg-accent/30 transition-colors"
              >
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-violet-500/10 text-xs font-bold text-violet-400">
                  {i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-foreground truncate">{idea.title}</div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="rounded-full bg-muted/50 border border-border px-2 py-0.5 text-[10px] text-muted-foreground">
                    {idea.tag}
                  </span>
                  <div className="flex items-center gap-1">
                    <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="text-xs font-semibold text-emerald-400">{idea.score}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right config panel */}
      <div className="w-80 shrink-0 border-l border-border bg-card/50 overflow-y-auto p-5 space-y-6">
        {/* Schedule */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-foreground">Schedule</h3>
            <button className="text-xs text-primary hover:underline">Edit Schedule</button>
          </div>
          <div className="rounded-md border border-border bg-muted/30 p-3 flex items-center gap-3">
            <CalendarDays className="h-4 w-4 text-muted-foreground shrink-0" />
            <div>
              <div className="text-sm font-medium text-foreground">Every Monday at 9:00 AM</div>
              <div className="text-xs text-muted-foreground mt-0.5">EST · After Trend Scout completes</div>
            </div>
          </div>
        </div>

        {/* Channel Connected */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Channel Connected</h3>
          <div className="rounded-md border border-border bg-muted/20 px-3 py-3 flex items-center gap-3">
            <div className="h-9 w-9 shrink-0 rounded-full bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center text-white text-sm font-bold">
              YT
            </div>
            <div className="flex-1">
              <div className="text-sm font-medium text-foreground">Your Channel</div>
              <div className="text-xs text-muted-foreground mt-0.5">847K subscribers</div>
            </div>
            <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
          </div>
        </div>

        {/* Focus Topics */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Focus Topics</h3>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {focusTopics.map((topic) => (
              <span
                key={topic}
                className="flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2.5 py-0.5 text-xs text-violet-400"
              >
                {topic}
                <button className="ml-0.5 text-violet-400/60 hover:text-violet-400">×</button>
              </span>
            ))}
          </div>
          <div className="flex gap-2 mt-2">
            <input
              type="text"
              placeholder="Add topic..."
              className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button className="flex items-center justify-center h-7 w-7 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Competitor Channels */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Competitor Channels</h3>
          <div className="space-y-2">
            {competitors.map((comp) => (
              <div key={comp} className="flex items-center gap-3 rounded-md border border-border bg-muted/20 px-3 py-2.5">
                <div className="h-7 w-7 shrink-0 rounded-full bg-muted flex items-center justify-center text-xs font-bold text-muted-foreground">
                  {comp[0]}
                </div>
                <span className="flex-1 text-sm text-foreground">{comp}</span>
                <button className="text-xs text-muted-foreground hover:text-red-400 transition-colors flex items-center gap-1">
                  <X className="h-3 w-3" />
                  Remove
                </button>
              </div>
            ))}
            <button className="w-full flex items-center justify-center gap-1.5 rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors">
              <Plus className="h-3.5 w-3.5" />
              Add Competitor
            </button>
          </div>
        </div>

        {/* Delivery */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Delivery</h3>
          <div className="space-y-2">
            {[
              { label: "Email Delivery", enabled: true },
              { label: "Slack Notification", enabled: true },
              { label: "Save to Dropbox", enabled: false },
            ].map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-md border border-border bg-muted/20 px-3 py-2.5">
                <span className="text-sm text-foreground">{item.label}</span>
                <button
                  className={cn(
                    "relative h-5 w-9 rounded-full transition-colors",
                    item.enabled ? "bg-primary" : "bg-muted"
                  )}
                >
                  <span
                    className={cn(
                      "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
                      item.enabled ? "left-4" : "left-0.5"
                    )}
                  />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Generate Brief */}
        <button className="w-full flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors">
          <Lightbulb className="h-4 w-4" />
          Generate Brief Now
        </button>
      </div>
    </div>
  );
}
