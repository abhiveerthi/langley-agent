import { CheckCircle2, XCircle, Terminal, ChevronRight } from "lucide-react";
import { botConnections } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const commandCategories = [
  {
    category: "Reports",
    commands: ["Run research report", "Generate brand brief", "Show last report"],
  },
  {
    category: "Content",
    commands: ["What's trending?", "Give me 5 video ideas", "Analyze my comments"],
  },
  {
    category: "Email",
    commands: ["Draft email for [video]", "Send blast", "Add subscriber [email]"],
  },
  {
    category: "Leads",
    commands: ["Find sponsor leads", "Show my leads", "Start outreach campaign"],
  },
  {
    category: "Files",
    commands: ["List my Dropbox reports", "Share last brief", "Upload to Dropbox"],
  },
  {
    category: "Tasks",
    commands: ["What's running?", "Show my tasks", "Run [agent]"],
  },
];

const platformInstructions: Record<string, string[]> = {
  discord: [
    "Click Connect to authorize Anthracite",
    "Choose your server and channel",
    "Start chatting with your agents",
  ],
  telegram: [
    "Click Connect to open Telegram",
    "Start a chat with @AnthraciteBot",
    "Send /start to link your account",
  ],
};

export default function BotConnectionsPage() {
  return (
    <div className="p-6 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Bot Connections</h1>
        <p className="mt-1 text-sm text-muted-foreground">Control your agents from anywhere</p>
      </div>

      {/* Platform cards */}
      <div className="space-y-5">
        {botConnections.map((bot) => {
          const isConnected = bot.status === "connected";
          const instructions = platformInstructions[bot.id];

          return (
            <div key={bot.id} className="rounded-lg border border-border bg-card p-6">
              <div className="flex items-start justify-between gap-4 mb-5">
                <div className="flex items-center gap-4">
                  <div className={cn("h-11 w-11 shrink-0 rounded-xl flex items-center justify-center text-white font-bold text-lg", bot.color)}>
                    {bot.name[0]}
                  </div>
                  <div>
                    <div className="flex items-center gap-2.5">
                      <h2 className="text-lg font-semibold text-foreground">{bot.name}</h2>
                      {isConnected ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 text-xs font-medium text-emerald-400">
                          <CheckCircle2 className="h-3 w-3" />
                          Connected
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-500/10 border border-zinc-500/20 px-2.5 py-0.5 text-xs font-medium text-zinc-400">
                          <XCircle className="h-3 w-3" />
                          Not Connected
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mt-0.5 max-w-xl">{bot.description}</p>
                  </div>
                </div>
              </div>

              {isConnected ? (
                <div className="space-y-5">
                  {/* Connection details */}
                  <div className="grid grid-cols-4 gap-4">
                    <div className={cn("rounded-md px-4 py-3", bot.bgLight)}>
                      <div className="text-xs text-muted-foreground mb-0.5">Workspace</div>
                      <div className={cn("text-sm font-semibold", bot.textColor)}>{bot.workspace}</div>
                    </div>
                    <div className={cn("rounded-md px-4 py-3", bot.bgLight)}>
                      <div className="text-xs text-muted-foreground mb-0.5">Channel</div>
                      <div className={cn("text-sm font-semibold font-mono", bot.textColor)}>{bot.channel}</div>
                    </div>
                    <div className={cn("rounded-md px-4 py-3", bot.bgLight)}>
                      <div className="text-xs text-muted-foreground mb-0.5">Last Interaction</div>
                      <div className={cn("text-sm font-semibold", bot.textColor)}>{bot.lastInteraction}</div>
                    </div>
                    <div className={cn("rounded-md px-4 py-3", bot.bgLight)}>
                      <div className="text-xs text-muted-foreground mb-0.5">Commands</div>
                      <div className={cn("text-sm font-semibold", bot.textColor)}>{bot.commandsAvailable} available</div>
                    </div>
                  </div>

                  {/* Recent commands */}
                  <div>
                    <h3 className="text-sm font-semibold text-foreground mb-2">Recent Commands</h3>
                    <div className="rounded-md border border-border divide-y divide-border">
                      {bot.recentCommands.map((cmd, i) => (
                        <div key={i} className="flex items-center gap-3 px-4 py-2.5">
                          <Terminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          <span className="flex-1 text-sm text-foreground font-mono">"{cmd.command}"</span>
                          <span className="text-xs text-muted-foreground whitespace-nowrap">{cmd.time}</span>
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-3">
                    <button className="flex items-center gap-1.5 rounded-md border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
                      View All Commands
                      <ChevronRight className="h-3.5 w-3.5" />
                    </button>
                    <button className="rounded-md border border-red-500/20 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-400 hover:bg-red-500/20 transition-colors">
                      Disconnect
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-5">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <span className="font-medium text-foreground">{bot.commandsAvailable} commands available</span>
                    after connecting
                  </div>

                  {/* How it works */}
                  <div>
                    <h3 className="text-sm font-semibold text-foreground mb-3">How it works</h3>
                    <div className="space-y-2">
                      {instructions?.map((step, i) => (
                        <div key={i} className="flex items-center gap-3">
                          <div className={cn("h-6 w-6 shrink-0 rounded-full flex items-center justify-center text-xs font-bold text-white", bot.color)}>
                            {i + 1}
                          </div>
                          <span className="text-sm text-muted-foreground">{step}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <button
                    className={cn(
                      "flex items-center gap-2 rounded-md px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90",
                      bot.color
                    )}
                  >
                    Connect {bot.name}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Available Commands reference */}
      <div>
        <h2 className="text-base font-semibold text-foreground mb-4">Available Commands</h2>
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-muted/30">
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground w-36">Category</th>
                <th className="px-5 py-3 text-left text-xs font-medium text-muted-foreground">Example Commands</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {commandCategories.map((cat) => (
                <tr key={cat.category} className="hover:bg-muted/20 transition-colors">
                  <td className="px-5 py-3.5">
                    <span className="text-sm font-medium text-foreground">{cat.category}</span>
                  </td>
                  <td className="px-5 py-3.5">
                    <div className="flex flex-wrap gap-2">
                      {cat.commands.map((cmd) => (
                        <span
                          key={cmd}
                          className="rounded-md border border-border bg-muted/30 px-2.5 py-1 text-xs text-foreground font-mono"
                        >
                          "{cmd}"
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
