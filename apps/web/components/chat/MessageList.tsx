"use client";

import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";
import type { ChatMessage } from "@/hooks/useChat";

interface MessageListProps {
  messages: ChatMessage[];
  /**
   * Forwarded from `useChat`. When true, the LAST assistant message in the
   * list is considered the in-progress one and renders a blinking caret;
   * all earlier bubbles render statically.
   */
  isStreaming?: boolean;
}

export function MessageList({ messages, isStreaming = false }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Index of the last assistant message — the only bubble allowed to wear
  // the caret. Tool-only or empty assistant slots still count: the caret
  // gives the user something to look at while the very first token of the
  // turn is still in flight.
  let lastAssistantIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") {
      lastAssistantIdx = i;
      break;
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 px-4 py-6">
      {messages.map((message, idx) => (
        <MessageBubble
          key={message.id}
          message={message}
          isStreaming={isStreaming && idx === lastAssistantIdx}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
