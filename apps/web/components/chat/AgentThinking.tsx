"use client";

import { Bot, Loader2 } from "lucide-react";

interface AgentThinkingProps {
  node: string;
}

export function AgentThinking({ node }: AgentThinkingProps) {
  // Format node name for display
  const displayName = node
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <div className="mx-auto max-w-3xl px-4 py-2">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
          <Bot className="h-4 w-4 text-foreground" />
        </div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>{displayName}...</span>
        </div>
      </div>
    </div>
  );
}
