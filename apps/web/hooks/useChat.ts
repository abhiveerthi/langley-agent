"use client";

import { useState, useCallback, useRef } from "react";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function authHeader(): Promise<Record<string, string>> {
  try {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    return session ? { Authorization: `Bearer ${session.access_token}` } : {};
  } catch {
    return {};
  }
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  toolCalls?: ToolCallEvent[];
  /**
   * Per-message structured outputs the backend emits via the
   * `structured_output` SSE event. Keyed by `kind` — currently
   * only "brief" (Strategist's WeeklyBrief), Publisher's "package" is on deck.
   * Renderers live in `components/structured/`.
   */
  structured?: Record<string, unknown>;
  createdAt: string;
}

/**
 * Strategist's WeeklyBrief — Pydantic schema in
 * packages/agents/strategist/agent.py mirrored here. The `compose_brief`
 * node fills this and `get_structured_outputs` surfaces it in the SSE
 * stream as `{kind: "brief", data: WeeklyBrief}`. Optional fields tolerate
 * older saved briefs that may lack newer keys.
 */
export interface WeeklyBrief {
  headline: string;
  ideas: VideoIdea[];
}

export interface VideoIdea {
  title: string;
  hook: string;
  why_now: string;
  confidence: "high" | "medium" | "low";
  rationale: string;
  citations?: string[];
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

/**
 * Emitted by the backend orchestrator when an agent's graph hits an
 * `interrupt_before` node and is waiting for human review. The frontend
 * inserts an inline approval card into the chat (see MessageList) and lets
 * the user approve / reject without leaving the conversation.
 *
 * Shape mirrors the SSE payload — see
 * apps/api/app/services/graph_orchestrator.py:_stream_until_done_or_pause.
 */
export interface PendingApproval {
  approval_id: string;
  thread_id: string;
  agent_slug: string;
  action_type: string;
  preview: string;
  payload: Record<string, unknown>;
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
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  /**
   * Drain an SSE response body into our message/state updates. Shared
   * between the fresh-message path (`sendMessage`) and the resume path
   * (`resumeApproval`) — same event grammar either way, so the parser
   * is too.
   */
  const consumeSseStream = useCallback(
    async (res: Response) => {
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
                  if (last && last.role === "assistant") {
                    return [
                      ...prev.slice(0, lastIdx),
                      { ...last, content: last.content + (event.data.content || "") },
                    ];
                  }
                  // Resume path: no assistant placeholder yet — create one.
                  return [
                    ...prev,
                    {
                      id: crypto.randomUUID(),
                      role: "assistant",
                      content: event.data.content || "",
                      toolCalls: [],
                      createdAt: new Date().toISOString(),
                    },
                  ];
                });
                setThinkingNode(null);
                break;

              case "tool_call_start":
                setMessages((prev) => {
                  const lastIdx = prev.length - 1;
                  const last = prev[lastIdx];
                  if (last && last.role === "assistant") {
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
                  if (last && last.role === "assistant" && last.toolCalls) {
                    return [
                      ...prev.slice(0, lastIdx),
                      {
                        ...last,
                        toolCalls: last.toolCalls.map((tc) =>
                          tc.id === event.data.id ? { ...tc, ...event.data } : tc
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

              case "waiting_approval":
                // Graph paused at an interrupt — surface the approval card
                // inline. Includes the action_payload (recipient/subject/body
                // for Brand Manager, original comment + reply for CM, etc.)
                // so the renderer doesn't need a second fetch.
                setPendingApproval({
                  approval_id: event.data.approval_id,
                  thread_id: event.data.thread_id,
                  agent_slug: event.data.agent_slug,
                  action_type: event.data.action_type,
                  preview: event.data.preview,
                  payload: event.data.payload || {},
                });
                setThinkingNode(null);
                break;

              case "approval_recorded":
                // Audit-trail event ahead of the resumed graph's tokens.
                // Hide the pending card immediately so the user doesn't
                // double-click; the resumed graph may emit a new
                // `waiting_approval` shortly (revise-pitch loop) and we'll
                // show that one fresh.
                setPendingApproval(null);
                break;

              case "structured_output":
                // Per-run typed payload (Strategist's WeeklyBrief, eventually
                // Publisher's package). Attach to the latest assistant message
                // so the renderer (MessageBubble) can show a rich card next
                // to the agent's prose. `kind` discriminates which renderer
                // fires — see components/structured/* for the per-kind UI.
                setMessages((prev) => {
                  const lastIdx = prev.length - 1;
                  const last = prev[lastIdx];
                  if (last && last.role === "assistant") {
                    return [
                      ...prev.slice(0, lastIdx),
                      {
                        ...last,
                        structured: {
                          ...(last.structured || {}),
                          [event.data.kind]: event.data.data,
                        },
                      },
                    ];
                  }
                  return prev;
                });
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
    },
    []
  );

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
        const auth = await authHeader();
        const res = await fetch(`${API_URL}/api/chat/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...auth,
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

        const newThreadId = res.headers.get("X-Thread-Id");
        if (newThreadId && !threadId) {
          setThreadId(newThreadId);
        }

        await consumeSseStream(res);
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
    [threadId, options.agentSlug, consumeSseStream]
  );

  /**
   * Resume a paused graph from the inline approval card. Streams the
   * continuation events back into the same chat — token/tool events flow
   * through the existing SSE handler. If the graph re-pauses (e.g. Brand
   * Manager's revise_pitch → approval_gate loop), `setPendingApproval`
   * fires again with the next approval id.
   */
  const resumeApproval = useCallback(
    async (
      approvalId: string,
      decision: "approved" | "rejected",
      feedback?: string
    ) => {
      setError(null);
      setIsStreaming(true);

      const abortController = new AbortController();
      abortRef.current = abortController;

      try {
        const auth = await authHeader();
        const path = decision === "approved"
          ? `/api/approvals/${approvalId}/approve`
          : `/api/approvals/${approvalId}/reject`;
        const body = decision === "rejected" && feedback
          ? JSON.stringify({ feedback })
          : undefined;
        const res = await fetch(`${API_URL}${path}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...auth,
          },
          body,
          signal: abortController.signal,
        });

        if (!res.ok) {
          throw new Error(`Resume failed: ${res.statusText}`);
        }

        await consumeSseStream(res);
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
    [consumeSseStream]
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
      setPendingApproval(null);
    },
    []
  );

  return {
    messages,
    isStreaming,
    threadId,
    thinkingNode,
    error,
    pendingApproval,
    sendMessage,
    resumeApproval,
    stopStreaming,
    loadThread,
  };
}
