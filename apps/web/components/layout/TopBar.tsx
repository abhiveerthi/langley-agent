"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { NotificationsBell } from "@/components/notifications/NotificationsBell";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type MeResponse = {
  user: {
    id: string;
    email: string;
    full_name: string | null;
    avatar_url: string | null;
    initials: string;
  };
  org: {
    id: string;
    name: string;
    slug: string;
  };
  role: string;
};

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
    team: "Team",
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
  const router = useRouter();
  const pageName = getPageName(pathname);
  const breadcrumb = getBreadcrumb(pathname);

  const [me, setMe] = useState<MeResponse | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const supabase = createClient();
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) return;
        const resp = await fetch(`${API}/api/me`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!resp.ok) return;
        const data: MeResponse = await resp.json();
        if (!cancelled) setMe(data);
      } catch {
        // Silent fail; the avatar shows fallback "??" until next mount.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Close the user menu on outside click / Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  async function handleSignOut() {
    setMenuOpen(false);
    const supabase = createClient();
    await supabase.auth.signOut();
    router.replace("/login");
    router.refresh();
  }

  const initials = me?.user.initials ?? "??";
  const avatarUrl = me?.user.avatar_url ?? null;
  const tooltipName = me?.user.full_name || me?.user.email || "Loading…";

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
        <NotificationsBell />
        <div ref={menuRef} className="relative">
          <button
            type="button"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            title={tooltipName}
            className="flex items-center rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {avatarUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={avatarUrl}
                alt={tooltipName}
                className="h-8 w-8 rounded-full object-cover"
              />
            ) : (
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
                {initials}
              </div>
            )}
          </button>
          {menuOpen && (
            <div
              role="menu"
              className="absolute right-0 top-full z-50 mt-2 w-56 overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-md"
            >
              <div className="border-b border-border px-3 py-2 text-xs">
                <div className="truncate font-medium text-foreground">
                  {me?.user.full_name || me?.user.email || "Loading…"}
                </div>
                {me?.org.name && (
                  <div className="truncate text-muted-foreground">{me.org.name}</div>
                )}
              </div>
              <button
                type="button"
                role="menuitem"
                onClick={handleSignOut}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground hover:bg-accent hover:text-accent-foreground"
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
