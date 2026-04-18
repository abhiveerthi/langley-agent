import Link from "next/link";
import { Plus, Radar, Lightbulb, Rocket, ArrowRight, CheckCircle2, Clock, MessageSquare } from "lucide-react";
import { agents, botConnections } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const agentColors: Record<string, { bg: string; icon: string; dot: string; border: string }> = {
  research: { bg: "bg-indigo-500/10", icon: "text-indigo-400", dot: "bg-indigo-500", border: "border-indigo-500/20" },
  intel:    { bg: "bg-violet-500/10", icon: "text-violet-400", dot: "bg-violet-500", border: "border-violet-500/20" },
  comms:    { bg: "bg-emerald-500/10", icon: "text-emerald-400", dot: "bg-emerald-500", border: "border-emerald-500/20" },
};

const agentIcons: Record<string, React.ElementType> = {
  research: Radar,
  intel:    Lightbulb,
  comms:    Rocket,
};

const activityLog = [
  { agentId: "research", text: "Trend Scout completed Research Brief #47", time: "Today 8:04 AM", href: "/app/tasks" },
  { agentId: "intel",    text: "Content Strategist completed Brand Brief #23", time: "Today 9:02 AM", href: "/app/tasks" },
  { agentId: "comms",    text: "Growth Engine discovered 4 new sponsor leads", time: "3 days ago", href: "/agents/comms" },
  { agentId: "research", text: "Trend Scout identified 12 new trends in Creator Economy", time: "Last Monday 8:11 AM", href: "/agents/research" },
  { agentId: "comms",    text: "Growth Engine drafted email blast for 'AI Tools' video", time: "4 days ago", href: "/agents/comms" },
];

export default function AgentsPage() {
  return (
    <div className="p-6 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Agents</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Autonomous AI workers running in the background for your channel
          </p>
        </div>
        <button className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90">
          <Plus className="h-4 w-4" />
          Deploy New Agent
        </button>
      </div>

      {/* Agent Cards */}
      <div className="grid gap-5 lg:grid-cols-3">
        {agents.map((agent) => {
          const colors = agentColors[agent.id];
          const Icon = agentIcons[agent.id];
          const href = `/agents/${agent.id}`;

          return (
            <div
              key={agent.id}
              className={cn(
                "rounded-lg border bg-card flex flex-col gap-5 p-5 transition-shadow hover:shadow-md",
                colors.border
              )}
            >
              {/* Top row */}
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", colors.bg)}>
                    <Icon className={cn("h-5 w-5", colors.icon)} />
                  </div>
                  <div>
                    <h2 className="font-semibold text-foreground leading-tight">{agent.name}</h2>
                    <p className="text-xs text-muted-foreground mt-0.5 leading-snug line-clamp-2">{agent.description}</p>
                  </div>
                </div>
                <div className="shrink-0">
                  {agent.status === "active" ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-400">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      Active
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-500/10 px-2.5 py-1 text-xs font-medium text-zinc-400">
                      <span className="h-1.5 w-1.5 rounded-full bg-zinc-400" />
                      Idle
                    </span>
                  )}
                </div>
              </div>

              {/* Stats row */}
              <div className="grid grid-cols-3 gap-2">
                <div className="rounded-md bg-muted/40 p-3 text-center">
                  <div className="text-lg font-bold text-foreground">{agent.reportsGenerated}</div>
                  <div className="text-[10px] text-muted-foreground mt-0.5 leading-tight">Reports</div>
                </div>
                <div className="rounded-md bg-muted/40 p-3 text-center">
                  <div className="text-lg font-bold text-foreground">{agent.trendsIdentified}</div>
                  <div className="text-[10px] text-muted-foreground mt-0.5 leading-tight">Insights</div>
                </div>
                <div className="rounded-md bg-muted/40 p-3 text-center">
                  <div className="text-[11px] font-bold text-foreground leading-tight">
                    {agent.schedule.split(",")[0]}
                  </div>
                  <div className="text-[10px] text-muted-foreground mt-0.5 leading-tight">Schedule</div>
                </div>
              </div>

              {/* Timing */}
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Last run: <span className="text-foreground/80">{agent.lastRun}</span></span>
                <span>Next: <span className="text-foreground/80">{agent.nextRun}</span></span>
              </div>

              {/* Connected sources */}
              <div className="flex flex-wrap gap-1.5">
                {agent.connectedSources.map((src) => (
                  <span
                    key={src}
                    className="rounded-full border border-border bg-muted/30 px-2 py-0.5 text-[10px] text-muted-foreground"
                  >
                    {src}
                  </span>
                ))}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2 border-t border-border pt-4 mt-auto">
                <Link
                  href={href}
                  className="flex-1 rounded-md border border-border px-3 py-1.5 text-center text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  Configure
                </Link>
                <Link
                  href={href}
                  className={cn(
                    "flex flex-1 items-center justify-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    colors.bg,
                    colors.icon,
                    "hover:opacity-80"
                  )}
                >
                  View Outputs
                  <ArrowRight className="h-3 w-3" />
                </Link>
              </div>
            </div>
          );
        })}
      </div>

      {/* Agent Activity */}
      <div>
        <h2 className="text-base font-semibold text-foreground mb-4">Agent Activity</h2>
        <div className="rounded-lg border border-border bg-card divide-y divide-border">
          {activityLog.map((item, i) => {
            const colors = agentColors[item.agentId];
            return (
              <div key={i} className="flex items-center gap-4 px-5 py-3.5">
                <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", colors.dot)} />
                <span className="flex-1 text-sm text-foreground/90">{item.text}</span>
                <span className="text-xs text-muted-foreground whitespace-nowrap">{item.time}</span>
                <Link href={item.href} className="text-xs text-primary hover:underline whitespace-nowrap">
                  View
                </Link>
              </div>
            );
          })}
        </div>
      </div>

      {/* Bot Connections teaser */}
      <div className="rounded-lg border border-border bg-card p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-foreground">Bot Connections</h2>
            <p className="text-xs text-muted-foreground mt-0.5">Control your agents from Slack, Discord, or Telegram</p>
          </div>
          <Link
            href="/app/agents/bots"
            className="flex items-center gap-1 text-sm font-medium text-primary hover:underline"
          >
            Manage Bot Connections
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
        <div className="grid grid-cols-3 gap-4">
          {botConnections.map((bot) => (
            <div key={bot.id} className="flex items-center gap-3 rounded-md border border-border bg-muted/20 px-4 py-3">
              <div className={cn("h-8 w-8 shrink-0 rounded-md flex items-center justify-center text-white font-bold text-xs", bot.color)}>
                {bot.name[0]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-foreground">{bot.name}</div>
                {bot.status === "connected" ? (
                  <div className="flex items-center gap-1 mt-0.5">
                    <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                    <span className="text-xs text-emerald-400">Connected</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-1 mt-0.5">
                    <Clock className="h-3 w-3 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">Not connected</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
