"use client";

import { usePathname } from "next/navigation";
import { Bell } from "lucide-react";

function getPageName(pathname: string): string {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return "Home";

  const last = segments[segments.length - 1];

  const nameMap: Record<string, string> = {
    dashboard: "Dashboard",
    chat: "Chat",
    clips: "Auto Clips",
    dubbing: "Voice Dubbing",
    subtitles: "Smart Subtitles",
    thumbnails: "Thumbnail Generator",
    scripts: "Script Writer",
    seo: "SEO Optimizer",
    comments: "Comment Intelligence",
    trends: "Trend Radar",
    crm: "Brand Deals",
    integrations: "Integrations",
    settings: "Settings",
    studio: "Studio",
    analytics: "Analytics",
    agents: "Agents",
    tasks: "Tasks",
    projects: "Projects",
    runs: "Runs",
    approvals: "Approvals",
  };

  return nameMap[last] ?? last.charAt(0).toUpperCase() + last.slice(1);
}

function getBreadcrumb(pathname: string): string[] {
  const segments = pathname.split("/").filter(Boolean);
  const nameMap: Record<string, string> = {
    studio: "Studio",
    analytics: "Analytics",
    dashboard: "Dashboard",
    chat: "Chat",
    crm: "Brand Deals",
    integrations: "Integrations",
    settings: "Settings",
  };

  if (segments.length <= 1) return [];

  return segments
    .slice(0, -1)
    .map((s) => nameMap[s] ?? s.charAt(0).toUpperCase() + s.slice(1));
}

export function TopBar() {
  const pathname = usePathname();
  const pageName = getPageName(pathname);
  const breadcrumb = getBreadcrumb(pathname);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-sm">
        {breadcrumb.map((crumb, i) => (
          <span key={i} className="flex items-center gap-1.5 text-muted-foreground">
            {crumb}
            <span className="text-muted-foreground/40">/</span>
          </span>
        ))}
        <span className="font-medium text-foreground">{pageName}</span>
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-2">
        <button className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
          <Bell className="h-4 w-4" />
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-primary" />
        </button>
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
          SR
        </div>
      </div>
    </header>
  );
}
