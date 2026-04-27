"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Compass, Megaphone, MessageCircle, Briefcase } from "lucide-react";
import { ChatWindow } from "@/components/chat/ChatWindow";

// Slugs registered in packages/agents/registry.py. Keep this list in sync;
// the chat page won't try to talk to anything not on it (it routes to a
// "coming soon" placeholder for unknown slugs — including "general", which
// is reserved for a future general-purpose bot).
const LIVE_AGENT_SLUGS = new Set([
  "strategist",
  "publisher",
  "community-manager",
  "brand-manager",
  "editor",
]);

const SPECIALIST_PICKS: { slug: string; label: string; icon: React.ElementType; href: string }[] = [
  { slug: "strategist", label: "Strategist", icon: Compass, href: "/app/agents/strategist" },
  { slug: "publisher", label: "Publisher", icon: Megaphone, href: "/app/agents/publisher" },
  { slug: "community-manager", label: "Community Manager", icon: MessageCircle, href: "/app/agents/community-manager" },
  { slug: "brand-manager", label: "Brand Manager", icon: Briefcase, href: "/app/agents/brand-manager" },
];

export default function ChatPage() {
  const params = useSearchParams();
  // Default agent: "general" — placeholder for the future general-purpose bot
  // (see ../../../memory: project_general_agent_reserved). Any other unknown
  // slug also falls through to the coming-soon view rather than 500'ing the API.
  const requestedAgent = params.get("agent") ?? "general";
  const isLive = LIVE_AGENT_SLUGS.has(requestedAgent);

  if (!isLive) {
    return <ComingSoonGeneral requestedAgent={requestedAgent} />;
  }

  return (
    <div className="h-full w-full">
      <ChatWindow agentSlug={requestedAgent} />
    </div>
  );
}

function ComingSoonGeneral({ requestedAgent }: { requestedAgent: string }) {
  // Any slug not in LIVE_AGENT_SLUGS lands here, including the reserved
  // "general" placeholder. Rather than blowing up against the backend
  // (which would 500 with "Unknown agent"), we surface a friendly hand-off
  // to the live specialists.
  const isReserved = requestedAgent === "general";

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="max-w-lg space-y-6 text-center">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            {isReserved ? "General assistant — coming soon" : "Agent not available"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {isReserved
              ? "We're building a general-purpose chat for everything that doesn't fit a specialist. Until then, pick one of your team below."
              : `"${requestedAgent}" isn't a registered agent yet. Pick one of the live specialists below.`}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3 text-left">
          {SPECIALIST_PICKS.map((s) => {
            const Icon = s.icon;
            return (
              <Link
                key={s.slug}
                href={s.href}
                className="rounded-lg border border-border bg-card px-4 py-3 text-sm transition-colors hover:border-border/80 hover:bg-accent"
              >
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-primary" />
                  <span className="font-medium text-foreground">{s.label}</span>
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
