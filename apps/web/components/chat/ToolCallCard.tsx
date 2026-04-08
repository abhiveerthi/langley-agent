"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { ToolCallEvent } from "@/hooks/useChat";
import { ChevronDown, ChevronRight, Wrench, Check, Loader2, AlertCircle } from "lucide-react";

interface ToolCallCardProps {
  toolCall: ToolCallEvent;
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);

  const statusIcon = {
    running: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400" />,
    success: <Check className="h-3.5 w-3.5 text-green-400" />,
    error: <AlertCircle className="h-3.5 w-3.5 text-destructive" />,
  };

  const statusBg = {
    running: "border-blue-500/30 bg-blue-500/5",
    success: "border-border bg-card",
    error: "border-destructive/30 bg-destructive/5",
  };

  return (
    <div
      className={cn(
        "rounded-md border text-sm",
        statusBg[toolCall.status]
      )}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2"
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="font-mono text-xs">{toolCall.tool}</span>
        <span className="ml-auto">{statusIcon[toolCall.status]}</span>
      </button>

      {expanded && (
        <div className="border-t border-border px-3 py-2 space-y-2">
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">Input</p>
            <pre className="rounded bg-background p-2 text-xs overflow-x-auto">
              {JSON.stringify(toolCall.input, null, 2)}
            </pre>
          </div>
          {toolCall.output !== undefined && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">Output</p>
              <pre className="rounded bg-background p-2 text-xs overflow-x-auto">
                {typeof toolCall.output === "string"
                  ? toolCall.output
                  : JSON.stringify(toolCall.output, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
