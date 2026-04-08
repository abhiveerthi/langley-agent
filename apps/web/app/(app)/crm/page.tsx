"use client";

import { useState } from "react";
import { Plus, Mail } from "lucide-react";
import { brandDeals } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const columns = [
  { id: "inbound", label: "Inbound", color: "text-blue-400" },
  { id: "reviewing", label: "Reviewing", color: "text-amber-400" },
  { id: "negotiating", label: "Negotiating", color: "text-violet-400" },
  { id: "active", label: "Active", color: "text-emerald-400" },
  { id: "complete", label: "Complete", color: "text-zinc-400" },
];

const brandColors: Record<string, string> = {
  N: "bg-zinc-800 text-zinc-200",
  E: "bg-emerald-900 text-emerald-300",
  S: "bg-red-900 text-red-300",
  H: "bg-violet-900 text-violet-300",
};

const mockEmails = [
  {
    brand: "NordVPN",
    initials: "N",
    from: "influencer@nordvpn.com",
    subject: "Partnership opportunity — $8,500 for YouTube integration",
    preview: "Hi Sean, we loved your recent AI tools video and think your audience would be a perfect fit for our VPN service. We're prepared to offer...",
    time: "1h ago",
  },
  {
    brand: "Skillshare",
    initials: "S",
    from: "brand@skillshare.com",
    subject: "Re: Skillshare mid-roll — contract revisions",
    preview: "Thanks for the quick turnaround on the draft. Our legal team has a few minor tweaks to the exclusivity clause on page 3...",
    time: "3h ago",
  },
];

const stats = [
  { label: "Active Deals", value: "2" },
  { label: "Pipeline Value", value: "$24,200" },
  { label: "This Month Revenue", value: "$11,300" },
];

export default function CRMPage() {
  const [showModal, setShowModal] = useState(false);

  const dealsByStatus = (status: string) =>
    brandDeals.filter((d) => d.status === status);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Brand Deals</h1>
          <p className="mt-1 text-sm text-muted-foreground">Manage your sponsorship pipeline</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" />
          Log New Deal
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4">
        {stats.map((stat) => (
          <div key={stat.label} className="rounded-lg border border-border bg-card p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{stat.label}</p>
            <p className="mt-2 text-3xl font-bold text-foreground">{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Kanban board */}
      <div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Pipeline
        </p>
        <div className="flex gap-4 overflow-x-auto pb-4">
          {columns.map((col) => {
            const deals = dealsByStatus(col.id);
            return (
              <div key={col.id} className="flex w-56 shrink-0 flex-col rounded-lg border border-border bg-muted/30">
                {/* Column header */}
                <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
                  <span className={cn("text-xs font-semibold uppercase tracking-wider", col.color)}>
                    {col.label}
                  </span>
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-xs font-medium text-muted-foreground">
                    {deals.length}
                  </span>
                </div>
                {/* Cards */}
                <div className="flex-1 space-y-2 p-2">
                  {deals.length === 0 && (
                    <div className="flex h-16 items-center justify-center rounded-md border border-dashed border-border">
                      <span className="text-xs text-muted-foreground">Empty</span>
                    </div>
                  )}
                  {deals.map((deal) => (
                    <div key={deal.id} className="rounded-lg border border-border bg-card p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <div
                          className={cn(
                            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold",
                            brandColors[deal.logo] ?? "bg-primary/20 text-primary"
                          )}
                        >
                          {deal.logo}
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-foreground">{deal.brand}</p>
                          <p className="text-xs font-semibold text-primary">{deal.rate}</p>
                        </div>
                      </div>
                      <div className="space-y-1.5">
                        <span className="inline-block rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                          {deal.deliverable}
                        </span>
                        <div className="flex items-center justify-between">
                          <span className="text-xs text-muted-foreground">Due: {deal.dueDate}</span>
                          <button className="flex items-center gap-1 text-xs text-primary hover:underline">
                            <Mail className="h-2.5 w-2.5" />
                            Email
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Recent Emails */}
      <div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Recent Emails
        </p>
        <div className="space-y-3">
          {mockEmails.map((email) => (
            <div key={email.brand} className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold",
                    brandColors[email.initials] ?? "bg-primary/20 text-primary"
                  )}
                >
                  {email.initials}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm font-medium text-foreground">{email.subject}</p>
                      <p className="text-xs text-muted-foreground">{email.from}</p>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">{email.time}</span>
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground line-clamp-2">{email.preview}</p>
                  <div className="mt-2 flex gap-2">
                    <button className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90">
                      Draft Reply
                    </button>
                    <button className="rounded-md border border-border px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
                      View Thread
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Simple modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-2xl">
            <h2 className="text-lg font-semibold text-foreground mb-4">Log New Deal</h2>
            <div className="space-y-4">
              {[
                { label: "Brand Name", placeholder: "e.g. Notion" },
                { label: "Rate", placeholder: "e.g. $5,000" },
                { label: "Deliverable", placeholder: "e.g. 30s integration" },
                { label: "Contact Email", placeholder: "brand@company.com" },
              ].map((field) => (
                <div key={field.label}>
                  <label className="mb-1.5 block text-xs font-medium text-foreground">{field.label}</label>
                  <input
                    placeholder={field.placeholder}
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none"
                  />
                </div>
              ))}
            </div>
            <div className="mt-5 flex gap-3">
              <button className="flex-1 rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                Add Deal
              </button>
              <button
                onClick={() => setShowModal(false)}
                className="flex-1 rounded-md border border-border py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
