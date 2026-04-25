"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ToolCallCard } from "./ToolCallCard";
import { BriefCard } from "@/components/structured/BriefCard";
import type { ChatMessage, WeeklyBrief } from "@/hooks/useChat";
import { cn } from "@/lib/utils";
import { Bot, User } from "lucide-react";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-md",
          isUser ? "bg-primary" : "bg-muted"
        )}
      >
        {isUser ? (
          <User className="h-4 w-4 text-primary-foreground" />
        ) : (
          <Bot className="h-4 w-4 text-foreground" />
        )}
      </div>

      <div className={cn("max-w-[80%] space-y-2", isUser && "text-right")}>
        {message.content && (
          <div
            className={cn(
              "rounded-lg px-4 py-2.5 text-sm",
              isUser
                ? "bg-primary text-primary-foreground"
                : "bg-card text-card-foreground border border-border"
            )}
          >
            {isUser ? (
              <p className="whitespace-pre-wrap">{message.content}</p>
            ) : (
              <div className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>
            )}
          </div>
        )}

        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="space-y-2">
            {message.toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} toolCall={tc} />
            ))}
          </div>
        )}

        {/* Structured outputs — agent-emitted typed payloads rendered
            alongside (or instead of) the markdown body. Each `kind` has a
            dedicated renderer; unknown kinds are silently skipped so the
            backend can introduce new types ahead of frontend support. */}
        {message.structured && Object.entries(message.structured).map(([kind, data]) => {
          if (kind === "brief") {
            return (
              <BriefCard key={kind} brief={data as WeeklyBrief} />
            );
          }
          return null;
        })}
      </div>
    </div>
  );
}
