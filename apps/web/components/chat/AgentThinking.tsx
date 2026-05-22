"use client";

import { Bot } from "lucide-react";
import { humanizeAgentNode } from "@/lib/agentNodes";

interface AgentThinkingProps {
  node: string;
}

/**
 * Shown inline between user message and the next streamed assistant
 * response. Three bouncing dots inside an assistant-styled bubble — the
 * same shell `MessageBubble` uses for completed messages, so the
 * transition from "thinking" to "answering" feels continuous rather
 * than two different shapes flickering.
 *
 * `node` is the raw graph node name; `humanizeAgentNode` maps it to
 * something like "Researching the brand" with a curated copy table.
 */
export function AgentThinking({ node }: AgentThinkingProps) {
  const label = humanizeAgentNode(node);

  return (
    <div className="mx-auto max-w-3xl px-4 py-2 chat-bubble-in">
      <div className="flex gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
          <Bot className="h-4 w-4 text-foreground" />
        </div>
        <div className="flex items-center gap-2.5 rounded-lg rounded-tl-sm border border-border bg-card px-3.5 py-2.5">
          <div className="flex items-end gap-1">
            <span className="chat-typing-dot h-1.5 w-1.5 rounded-full bg-primary" style={{ animationDelay: "0ms" }} />
            <span className="chat-typing-dot h-1.5 w-1.5 rounded-full bg-primary" style={{ animationDelay: "160ms" }} />
            <span className="chat-typing-dot h-1.5 w-1.5 rounded-full bg-primary" style={{ animationDelay: "320ms" }} />
          </div>
          <span className="text-xs text-muted-foreground">{label}…</span>
        </div>
      </div>
    </div>
  );
}
