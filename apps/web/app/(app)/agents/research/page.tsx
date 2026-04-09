"use client";

import Link from "next/link";
import {
  ArrowLeft,
  FileText,
  Download,
  Eye,
  Radar,
  CalendarDays,
  ToggleRight,
  Plus,
  CheckCircle2,
  Clock,
  XCircle,
} from "lucide-react";
import { researchReports } from "@/lib/mock-data";
import { cn } from "@/lib/utils";
import { MiniChat } from "@/components/chat/MiniChat";

const activityLogs = [
  { time: "Today 8:04 AM", action: "Ran weekly research sweep across all sources", duration: "4m 32s", status: "success" },
  { time: "Today 8:00 AM", action: "Schedule triggered — starting research run", duration: "0m 02s", status: "success" },
  { time: "Mon Mar 31, 8:03 AM", action: "Ran weekly research sweep across all sources", duration: "3m 58s", status: "success" },
  { time: "Mon Mar 24, 8:01 AM", action: "Ran weekly research sweep across all sources", duration: "4m 12s", status: "success" },
  { time: "Mon Mar 17, 8:05 AM", action: "Ran weekly research sweep across all sources", duration: "3m 44s", status: "success" },
];

const dataSources = [
  { name: "Twitter/X", enabled: true },
  { name: "YouTube Comments", enabled: true },
  { name: "Reddit", enabled: true },
  { name: "News RSS", enabled: false },
];

const keywords = [
  "AI tools", "YouTube growth", "creator economy", "passive income",
  "YouTube Shorts", "content creation", "video editing", "online business",
];

export default function ResearchAgentPage() {
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
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-500/10 border border-indigo-500/20">
              <Radar className="h-5 w-5 text-indigo-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Trend Scout</h1>
              <p className="text-sm text-muted-foreground">Monitors X/Twitter, Reddit, and YouTube comments for trending topics</p>
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
            { label: "Reports Generated", value: "47" },
            { label: "Trends Found", value: "234" },
            { label: "Data Points Processed", value: "12.4K" },
          ].map((stat) => (
            <div key={stat.label} className="rounded-lg border border-border bg-card p-4">
              <div className="text-2xl font-bold text-foreground">{stat.value}</div>
              <div className="text-xs text-muted-foreground mt-1">{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Recent Reports */}
        <div>
          <h2 className="text-base font-semibold text-foreground mb-3">Recent Reports</h2>
          <div className="space-y-3">
            {researchReports.map((report, i) => (
              <div key={i} className="rounded-lg border border-border bg-card p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-500/10">
                      <FileText className="h-4 w-4 text-indigo-400" />
                    </div>
                    <div>
                      <div className="font-medium text-foreground text-sm">{report.title}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">{report.date} · {report.size}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
                      <Eye className="h-3.5 w-3.5" />
                      View
                    </button>
                    <button className="flex items-center gap-1.5 rounded-md bg-indigo-500/10 border border-indigo-500/20 px-3 py-1.5 text-xs font-medium text-indigo-400 hover:bg-indigo-500/20 transition-colors">
                      <Download className="h-3.5 w-3.5" />
                      Download PDF
                    </button>
                  </div>
                </div>
                <div className="mt-3 space-y-1.5 pl-12">
                  {report.highlights.map((h, j) => (
                    <div key={j} className="flex items-start gap-2 text-xs text-muted-foreground">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-indigo-400" />
                      {h}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Recent Activity */}
        <div>
          <h2 className="text-base font-semibold text-foreground mb-3">Recent Activity</h2>
          <div className="rounded-lg border border-border bg-card divide-y divide-border">
            {activityLogs.map((log, i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-3">
                {log.status === "success" ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                ) : (
                  <XCircle className="h-4 w-4 shrink-0 text-red-400" />
                )}
                <span className="text-xs text-muted-foreground whitespace-nowrap w-36 shrink-0">{log.time}</span>
                <span className="flex-1 text-sm text-foreground/90">{log.action}</span>
                <span className="text-xs text-muted-foreground whitespace-nowrap">{log.duration}</span>
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
              <div className="text-sm font-medium text-foreground">Every Monday at 8:00 AM</div>
              <div className="text-xs text-muted-foreground mt-0.5">EST · Next run in 3 days</div>
            </div>
          </div>
        </div>

        {/* Data Sources */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Data Sources</h3>
          <div className="space-y-2">
            {dataSources.map((src) => (
              <div key={src.name} className="flex items-center justify-between rounded-md border border-border bg-muted/20 px-3 py-2.5">
                <span className="text-sm text-foreground">{src.name}</span>
                <button
                  className={cn(
                    "relative h-5 w-9 rounded-full transition-colors",
                    src.enabled ? "bg-primary" : "bg-muted"
                  )}
                >
                  <span
                    className={cn(
                      "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
                      src.enabled ? "left-4" : "left-0.5"
                    )}
                  />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Keywords */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Keywords</h3>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {keywords.map((kw) => (
              <span
                key={kw}
                className="flex items-center gap-1 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-0.5 text-xs text-indigo-400"
              >
                {kw}
                <button className="ml-0.5 text-indigo-400/60 hover:text-indigo-400">×</button>
              </span>
            ))}
          </div>
          <div className="flex gap-2 mt-2">
            <input
              type="text"
              placeholder="Add keyword..."
              className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button className="flex items-center justify-center h-7 w-7 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
              <Plus className="h-3.5 w-3.5" />
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
              { label: "Save to Dropbox", enabled: true },
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

        {/* Run Now */}
        <button className="w-full flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors">
          <Radar className="h-4 w-4" />
          Run Now
        </button>
      </div>

      {/* Mini Chat */}
      <MiniChat agentSlug="research" agentName="Trend Scout" />
    </div>
  );
}
