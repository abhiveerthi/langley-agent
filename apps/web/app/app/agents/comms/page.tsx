"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ArrowLeft,
  Rocket,
  Mail,
  Users,
  ExternalLink,
  Search,
  CheckCircle2,
  Plus,
} from "lucide-react";
import { sponsorLeads } from "@/lib/mock-data";
import { cn } from "@/lib/utils";
import { MiniChat } from "@/components/chat/MiniChat";

const emailCampaigns = [
  { id: "1", name: "New Video Blast — 'AI Tools Changed My Workflow'", status: "sent", sent: 847, openRate: "38%", date: "Yesterday" },
  { id: "2", name: "Weekly Newsletter — Apr 1, 2026", status: "sent", sent: 832, openRate: "41%", date: "Apr 1" },
  { id: "3", name: "Sponsorship Announcement — Epidemic Sound", status: "draft", sent: 0, openRate: "—", date: "Draft" },
];

const subscribers = [
  { email: "alex.johnson@gmail.com", name: "Alex Johnson", joined: "Mar 14" },
  { email: "sarah.m@proton.me", name: "Sarah M.", joined: "Mar 22" },
  { email: "devsteve@outlook.com", name: "DevSteve", joined: "Apr 1" },
  { email: "creativecathy@gmail.com", name: "Cathy R.", joined: "Apr 3" },
  { email: "youtubegeek99@gmail.com", name: "YouTubeGeek99", joined: "Apr 6" },
];

const fitColors: Record<string, string> = {
  High: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  Medium: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  Low: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
};

const statusColors: Record<string, string> = {
  New: "bg-indigo-500/10 text-indigo-400",
  Contacted: "bg-amber-500/10 text-amber-400",
  Replied: "bg-emerald-500/10 text-emerald-400",
};

type Tab = "campaigns" | "leads" | "subscribers";

export default function CommsAgentPage() {
  const [activeTab, setActiveTab] = useState<Tab>("campaigns");

  return (
    <div className="flex h-full min-h-0">
      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <div>
          <Link
            href="/app/agents"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3 transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            All Agents
          </Link>
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 border border-emerald-500/20">
              <Rocket className="h-5 w-5 text-emerald-400" />
            </div>
            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Growth Engine</h1>
              <p className="text-sm text-muted-foreground">Automates email campaigns, discovers sponsorship leads, and manages outreach</p>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-zinc-500/30 bg-zinc-500/10 px-3 py-1.5">
              <span className="h-2 w-2 rounded-full bg-zinc-400" />
              <span className="text-sm font-medium text-zinc-400">Idle</span>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "Emails Sent", value: "284" },
            { label: "Leads Found", value: "64" },
            { label: "Open Rate", value: "38%" },
          ].map((stat) => (
            <div key={stat.label} className="rounded-lg border border-border bg-card p-4">
              <div className="text-2xl font-bold text-foreground">{stat.value}</div>
              <div className="text-xs text-muted-foreground mt-1">{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Tabs */}
        <div>
          <div className="flex border-b border-border mb-4">
            {(["campaigns", "leads", "subscribers"] as Tab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={cn(
                  "px-4 py-2.5 text-sm font-medium capitalize transition-colors border-b-2 -mb-px",
                  activeTab === tab
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {tab === "campaigns" ? "Email Campaigns" : tab === "leads" ? "Sponsor Leads" : "Subscribers"}
              </button>
            ))}
          </div>

          {/* Email Campaigns */}
          {activeTab === "campaigns" && (
            <div className="space-y-3">
              {emailCampaigns.map((campaign) => (
                <div key={campaign.id} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10">
                        <Mail className="h-4 w-4 text-emerald-400" />
                      </div>
                      <div>
                        <div className="text-sm font-medium text-foreground">{campaign.name}</div>
                        <div className="text-xs text-muted-foreground mt-0.5">{campaign.date}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <div className="text-right">
                        <div className="text-xs text-muted-foreground">Sent</div>
                        <div className="text-sm font-semibold text-foreground">{campaign.sent.toLocaleString()}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-xs text-muted-foreground">Open Rate</div>
                        <div className="text-sm font-semibold text-foreground">{campaign.openRate}</div>
                      </div>
                      <span
                        className={cn(
                          "rounded-full px-2.5 py-1 text-xs font-medium",
                          campaign.status === "sent"
                            ? "bg-emerald-500/10 text-emerald-400"
                            : "bg-zinc-500/10 text-zinc-400"
                        )}
                      >
                        {campaign.status === "sent" ? "Sent" : "Draft"}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
              <button className="w-full flex items-center justify-center gap-1.5 rounded-lg border border-dashed border-border px-4 py-3 text-sm text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors">
                <Plus className="h-4 w-4" />
                New Campaign
              </button>
            </div>
          )}

          {/* Sponsor Leads */}
          {activeTab === "leads" && (
            <div className="rounded-lg border border-border bg-card overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/30">
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Company</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Role</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Website</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Fit</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground">Status</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {sponsorLeads.map((lead) => (
                    <tr key={lead.id} className="hover:bg-muted/20 transition-colors">
                      <td className="px-4 py-3 font-medium text-foreground">{lead.company}</td>
                      <td className="px-4 py-3 text-muted-foreground">{lead.role}</td>
                      <td className="px-4 py-3">
                        <a
                          href={`https://${lead.website}`}
                          className="flex items-center gap-1 text-primary hover:underline text-xs"
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {lead.website}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn("rounded-full border px-2 py-0.5 text-xs font-medium", fitColors[lead.fit])}>
                          {lead.fit}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn("rounded-full px-2.5 py-1 text-xs font-medium", statusColors[lead.status])}>
                          {lead.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <button className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
                          <Mail className="h-3 w-3" />
                          Compose
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Subscribers */}
          {activeTab === "subscribers" && (
            <div className="space-y-4">
              <div className="flex items-center gap-4">
                <div className="rounded-lg border border-border bg-card px-5 py-4 flex items-center gap-3">
                  <Users className="h-5 w-5 text-emerald-400" />
                  <div>
                    <div className="text-2xl font-bold text-foreground">847</div>
                    <div className="text-xs text-muted-foreground">Total Subscribers</div>
                  </div>
                </div>
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder="Search subscribers..."
                    className="w-full rounded-md border border-border bg-background pl-9 pr-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>
              <div className="rounded-lg border border-border bg-card divide-y divide-border">
                {subscribers.map((sub) => (
                  <div key={sub.email} className="flex items-center gap-3 px-4 py-3">
                    <div className="h-8 w-8 shrink-0 rounded-full bg-muted flex items-center justify-center text-xs font-semibold text-muted-foreground">
                      {sub.name[0]}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-foreground">{sub.name}</div>
                      <div className="text-xs text-muted-foreground truncate">{sub.email}</div>
                    </div>
                    <div className="text-xs text-muted-foreground">Joined {sub.joined}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Right config panel */}
      <div className="w-80 shrink-0 border-l border-border bg-card/50 overflow-y-auto p-5 space-y-6">
        {/* Gmail */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Gmail</h3>
          <div className="rounded-md border border-border bg-muted/20 px-3 py-3 flex items-center gap-3">
            <div className="h-9 w-9 shrink-0 rounded-full bg-gradient-to-br from-red-400 to-orange-400 flex items-center justify-center text-white text-xs font-bold">
              G
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-foreground truncate">hello@yourchannel.com</div>
              <div className="text-xs text-muted-foreground mt-0.5">Gmail · Connected</div>
            </div>
            <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
          </div>
        </div>

        {/* Lead Discovery */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Lead Discovery</h3>
          <div className="space-y-2.5">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Search Query</label>
              <input
                type="text"
                defaultValue="YouTube creators AI tools sponsorship"
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Frequency</label>
              <select className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary">
                <option>Weekly</option>
                <option>Bi-weekly</option>
                <option>On demand</option>
              </select>
            </div>
            <button className="w-full rounded-md bg-emerald-500/10 border border-emerald-500/20 px-3 py-2 text-xs font-medium text-emerald-400 hover:bg-emerald-500/20 transition-colors">
              Find Leads
            </button>
          </div>
        </div>

        {/* Campaign Settings */}
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">Campaign Settings</h3>
          <div className="space-y-2">
            {[
              { label: "Auto-draft on new video", enabled: true },
              { label: "Require approval before send", enabled: true },
              { label: "A/B Testing", enabled: false },
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

        {/* Run Lead Search */}
        <button className="w-full flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors">
          <Search className="h-4 w-4" />
          Run Lead Search
        </button>
      </div>

      {/* Mini Chat */}
      <MiniChat agentSlug="comms" agentName="Growth Engine" />
    </div>
  );
}
