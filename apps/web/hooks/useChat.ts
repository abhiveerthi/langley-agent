"use client";

import { useState, useCallback, useRef } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  toolCalls?: ToolCallEvent[];
  createdAt: string;
}

export interface ToolCallEvent {
  id: string;
  tool: string;
  input: Record<string, unknown>;
  output?: unknown;
  status: "running" | "success" | "error";
  started_at?: string;
  completed_at?: string;
}

interface UseChatOptions {
  threadId?: string;
  agentSlug?: string;
}

export function useChat(options: UseChatOptions = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [threadId, setThreadId] = useState<string | undefined>(options.threadId);
  const [thinkingNode, setThinkingNode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(
    async (content: string) => {
      setError(null);
      const userMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        createdAt: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMessage]);
      setIsStreaming(true);

      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        toolCalls: [],
        createdAt: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, assistantMessage]);

      const abortController = new AbortController();
      abortRef.current = abortController;

      try {
        const res = await fetch(`${API_URL}/api/chat/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            message: content,
            thread_id: threadId,
            agent_slug: options.agentSlug || "general",
          }),
          signal: abortController.signal,
        });

        if (!res.ok) {
          throw new Error(`Stream failed: ${res.statusText}`);
        }

        // Capture thread ID from headers
        const newThreadId = res.headers.get("X-Thread-Id");
        if (newThreadId && !threadId) {
          setThreadId(newThreadId);
        }

        const reader = res.body?.getReader();
        const decoder = new TextDecoder();

        if (!reader) throw new Error("No reader available");

        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const jsonStr = line.slice(6).trim();
            if (!jsonStr || jsonStr === "[DONE]") continue;

            try {
              const event = JSON.parse(jsonStr);

              switch (event.type) {
                case "token":
                  setMessages((prev) => {
                    const lastIdx = prev.length - 1;
                    const last = prev[lastIdx];
                    if (last.role === "assistant") {
                      return [
                        ...prev.slice(0, lastIdx),
                        { ...last, content: last.content + (event.data.content || "") },
                      ];
                    }
                    return prev;
                  });
                  setThinkingNode(null);
                  break;

                case "tool_call_start":
                  setMessages((prev) => {
                    const lastIdx = prev.length - 1;
                    const last = prev[lastIdx];
                    if (last.role === "assistant") {
                      return [
                        ...prev.slice(0, lastIdx),
                        { ...last, toolCalls: [...(last.toolCalls || []), event.data] },
                      ];
                    }
                    return prev;
                  });
                  break;

                case "tool_call_end":
                  setMessages((prev) => {
                    const lastIdx = prev.length - 1;
                    const last = prev[lastIdx];
                    if (last.role === "assistant" && last.toolCalls) {
                      return [
                        ...prev.slice(0, lastIdx),
                        {
                          ...last,
                          toolCalls: last.toolCalls.map((tc) =>
                            tc.id === event.data.id
                              ? { ...tc, ...event.data }
                              : tc
                          ),
                        },
                      ];
                    }
                    return prev;
                  });
                  break;

                case "agent_thinking":
                  setThinkingNode(event.data.node);
                  break;

                case "error":
                  setError(event.data.message);
                  break;

                case "done":
                  break;
              }
            } catch {
              // skip malformed JSON
            }
          }
        }
      } catch (err) {
        if (err instanceof Error && err.name !== "AbortError") {
          setError(err.message);
        }
      } finally {
        setIsStreaming(false);
        setThinkingNode(null);
        abortRef.current = null;
      }
    },
    [threadId, options.agentSlug]
  );

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const loadThread = useCallback(
    async (id: string) => {
      const res = await fetch(`${API_URL}/api/chat/threads/${id}`);

      if (!res.ok) return;
      const data = await res.json();
      setThreadId(id);
      setMessages(
        (data.messages || []).map((m: Record<string, unknown>) => ({
          id: m.id as string,
          role: m.role as string,
          content: (m.content as string) || "",
          toolCalls: [],
          createdAt: m.created_at as string,
        }))
      );
    },
    []
  );

  return {
    messages,
    isStreaming,
    threadId,
    thinkingNode,
    error,
    sendMessage,
    stopStreaming,
    loadThread,
  };
}
