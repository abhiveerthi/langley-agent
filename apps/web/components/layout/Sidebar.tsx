"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Zap,
  Plus,
  MessageSquare,
  Scissors,
  Languages,
  Subtitles,
  Image,
  FileText,
  Search,
  BarChart3,
  MessageCircle,
  TrendingUp,
  Briefcase,
  Plug,
  Settings,
  Compass,
  Megaphone,
  ListChecks,
  CheckSquare,
  Send,
} from "lucide-react";
import { cn } from "@/lib/utils";

const studioItems = [
  { label: "Auto Clips", href: "/app/studio/clips", icon: Scissors },
  { label: "Dubbing", href: "/app/studio/dubbing", icon: Languages },
  { label: "Subtitles", href: "/app/studio/subtitles", icon: Subtitles },
  { label: "Thumbnails", href: "/app/studio/thumbnails", icon: Image },
  { label: "Script Writer", href: "/app/studio/scripts", icon: FileText },
  { label: "SEO Optimizer", href: "/app/studio/seo", icon: Search },
];

// The live agent roster — these are the registered agents in the backend.
// Each link goes to the agent's dashboard, which embeds a MiniChat for
// in-context conversations. The "general" assistant slug is reserved for a
// future general-purpose bot — kept off the sidebar until it ships.
const agentItems = [
  { label: "Strategist", href: "/app/agents/strategist", icon: Compass },
  { label: "Publisher", href: "/app/agents/publisher", icon: Megaphone },
  { label: "Community Manager", href: "/app/agents/community-manager", icon: MessageCircle },
  { label: "Brand Manager", href: "/app/agents/brand-manager", icon: Briefcase },
];

const analyzeItems = [
  { label: "Dashboard", href: "/app/dashboard", icon: BarChart3 },
  { label: "Comments", href: "/app/analytics/comments", icon: MessageCircle },
  { label: "Trends", href: "/app/analytics/trends", icon: TrendingUp },
];

// Dispatch is where the agents reach out from — Slack today, Discord/Telegram
// later. Visually grouped with Integrations because both are about external
// connections, not in the Agents section because it's a configuration concern,
// not a per-agent surface.
const businessItems = [
  { label: "Brand Deals", href: "/app/crm", icon: Briefcase },
  { label: "Integrations", href: "/app/integrations", icon: Plug },
  { label: "Dispatch", href: "/app/agents/bots", icon: Send },
];

function NavItem({ label, href, icon: Icon, exact }: { label: string; href: string; icon: React.ElementType; exact?: boolean }) {
  const pathname = usePathname();
  const isActive = exact ? pathname === href : pathname.startsWith(href);

  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
        isActive
          ? "bg-primary/15 text-primary font-medium"
          : "text-muted-foreground hover:bg-accent hover:text-foreground"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {label}
    </Link>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-3 pb-1 pt-4 text-xs font-semibold uppercase tracking-widest text-muted-foreground/60">
      {children}
    </p>
  );
}

function TasksItem() {
  const pathname = usePathname();
  const isActive = pathname === "/app/tasks";
  return (
    <Link
      href="/app/tasks"
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
        isActive
          ? "bg-primary/15 text-primary font-medium"
          : "text-muted-foreground hover:bg-accent hover:text-foreground"
      )}
    >
      <ListChecks className="h-4 w-4 shrink-0" />
      Tasks
      <span className="ml-auto flex h-4 min-w-4 items-center justify-center rounded-full bg-primary/20 text-[10px] font-medium text-primary">3</span>
    </Link>
  );
}

function ApprovalsItem() {
  const pathname = usePathname();
  const isActive = pathname.startsWith("/app/approvals");
  return (
    <Link
      href="/app/approvals"
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
        isActive
          ? "bg-primary/15 text-primary font-medium"
          : "text-muted-foreground hover:bg-accent hover:text-foreground"
      )}
    >
      <CheckSquare className="h-4 w-4 shrink-0" />
      Approvals
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const isChatActive = pathname.startsWith("/app/chat");

  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col border-r border-border bg-sidebar">
      {/* Logo */}
      <div className="flex items-center gap-2.5 border-b border-border px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <Zap className="h-4 w-4" />
        </div>
        <span className="text-base font-semibold tracking-tight text-foreground">Backroom</span>
      </div>

      {/* New Chat CTA */}
      <div className="px-3 py-3">
        <Link
          href="/app/chat"
          className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" />
          New Chat
        </Link>
      </div>

      {/* Chat shortcut */}
      <div className="px-3 pb-1">
        <Link
          href="/app/chat"
          className={cn(
            "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
            isChatActive
              ? "bg-primary/15 text-primary font-medium"
              : "text-muted-foreground hover:bg-accent hover:text-foreground"
          )}
        >
          <MessageSquare className="h-4 w-4 shrink-0" />
          Chat
        </Link>
      </div>

      {/* Nav sections */}
      <nav className="flex-1 overflow-y-auto px-3 pb-3">
        <SectionLabel>Agents</SectionLabel>
        {agentItems.map((item) => (
          <NavItem key={item.href} {...item} />
        ))}

        <SectionLabel>Work</SectionLabel>
        <TasksItem />
        <ApprovalsItem />

        <SectionLabel>Analyze</SectionLabel>
        {analyzeItems.map((item) => (
          <NavItem key={item.href} {...item} />
        ))}

        <SectionLabel>Business</SectionLabel>
        {businessItems.map((item) => (
          <NavItem key={item.href} {...item} />
        ))}

        <SectionLabel>Studio</SectionLabel>
        {studioItems.map((item) => (
          <NavItem key={item.href} {...item} />
        ))}
      </nav>

      {/* Bottom pinned settings */}
      <div className="border-t border-border px-3 py-3">
        <NavItem label="Settings" href="/app/settings" icon={Settings} />
      </div>
    </aside>
  );
}
