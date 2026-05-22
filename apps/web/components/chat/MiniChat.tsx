"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  MessageSquare,
  Send,
  Square,
  X,
  Minus,
  ChevronUp,
  Plus,
  History,
} from "lucide-react";
import { useChat, listThreads, type ThreadSummary } from "@/hooks/useChat";
import { humanizeAgentNode } from "@/lib/agentNodes";
import { cn } from "@/lib/utils";
import { MarkdownBody } from "./MarkdownBody";

interface MiniChatProps {
  agentSlug: string;
  agentName: string;
  accentColor?: string;
}

/**
 * localStorage key for the active thread id, scoped per agent. Lets the
 * floating panel re-open onto the same chat after a navigation or page
 * reload without needing a global store. One key per agent so each agent's
 * panel keeps its own conversation.
 */
const activeThreadKey = (agentSlug: string) => `marcus:chat:active:${agentSlug}`;

export function MiniChat({ agentSlug, agentName }: MiniChatProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [inputValue, setInputValue] = useState("");
  const hydratedRef = useRef(false);

  const {
    messages,
    isStreaming,
    thinkingNode,
    error,
    threadId,
    sendMessage,
    stopStreaming,
    loadThread,
    newChat,
  } = useChat({ agentSlug });

  // One-time hydration: if we saved an active thread for this agent last
  // session, reload it on mount so navigating back to the page doesn't
  // wipe the chat. Guarded by `hydratedRef` so the effect doesn't refire
  // when `loadThread` identity changes.
  useEffect(() => {
    if (hydratedRef.current || typeof window === "undefined") return;
    hydratedRef.current = true;
    const saved = window.localStorage.getItem(activeThreadKey(agentSlug));
    if (saved) {
      void loadThread(saved);
    }
  }, [agentSlug, loadThread]);

  // Persist the active thread id whenever the hook mints a new one (after
  // the first send) or we explicitly load one. Clearing it on `newChat`
  // is handled by the button below — once a fresh send happens, this
  // effect writes the new id.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (threadId) {
      window.localStorage.setItem(activeThreadKey(agentSlug), threadId);
    }
  }, [threadId, agentSlug]);

  const refreshThreads = useCallback(async () => {
    const list = await listThreads(agentSlug);
    setThreads(list);
  }, [agentSlug]);

  // Pull the history list when the user opens the sidebar, and again after
  // a turn finishes so a freshly-created thread shows up immediately.
  useEffect(() => {
    if (showHistory) void refreshThreads();
  }, [showHistory, refreshThreads]);

  useEffect(() => {
    if (!isStreaming && threadId) void refreshThreads();
  }, [isStreaming, threadId, refreshThreads]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinkingNode]);

  useEffect(() => {
    if (isOpen && !isMinimized && !showHistory) {
      inputRef.current?.focus();
    }
  }, [isOpen, isMinimized, showHistory]);

  const handleSubmit = useCallback(() => {
    const trimmed = inputValue.trim();
    if (!trimmed || isStreaming) return;
    sendMessage(trimmed);
    setInputValue("");
  }, [inputValue, isStreaming, sendMessage]);

  // Only the last assistant message wears the streaming caret. Earlier
  // assistant turns are completed history and render statically.
  let lastAssistantIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "assistant") {
      lastAssistantIdx = i;
      break;
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleNewChat = useCallback(() => {
    newChat();
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(activeThreadKey(agentSlug));
    }
    setShowHistory(false);
  }, [agentSlug, newChat]);

  const handleSelectThread = useCallback(
    (id: string) => {
      void loadThread(id);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(activeThreadKey(agentSlug), id);
      }
      setShowHistory(false);
    },
    [agentSlug, loadThread]
  );

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className={cn(
          "fixed bottom-5 right-5 z-50 flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium shadow-lg transition-all hover:scale-105",
          "bg-primary text-primary-foreground hover:bg-primary/90"
        )}
      >
        <MessageSquare className="h-4 w-4" />
        Chat with {agentName}
      </button>
    );
  }

  if (isMinimized) {
    return (
      <div className="fixed bottom-5 right-5 z-50 flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 shadow-lg">
        <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-foreground">{agentName}</span>
        {messages.length > 0 && (
          <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-primary/20 text-[10px] font-medium text-primary">
            {messages.filter((m) => m.role === "assistant").length}
          </span>
        )}
        <button
          onClick={() => setIsMinimized(false)}
          className="ml-1 text-muted-foreground hover:text-foreground"
        >
          <ChevronUp className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={() => {
            setIsOpen(false);
            setIsMinimized(false);
          }}
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="fixed bottom-5 right-5 z-50 flex h-[480px] w-[380px] flex-col rounded-xl border border-border bg-background shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">{agentName}</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowHistory((v) => !v)}
            title={showHistory ? "Hide history" : "Show history"}
            className={cn(
              "rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground",
              showHistory && "bg-accent text-foreground"
            )}
          >
            <History className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={handleNewChat}
            title="Start a new chat"
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => setIsMinimized(true)}
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Minus className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => {
              setIsOpen(false);
              setIsMinimized(false);
            }}
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {showHistory ? (
        <ThreadHistoryList
          threads={threads}
          activeId={threadId}
          onSelect={handleSelectThread}
          onNewChat={handleNewChat}
          agentName={agentName}
        />
      ) : (
        <>
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {messages.length === 0 && (
              <div className="flex h-full items-center justify-center">
                <div className="text-center px-4">
                  <MessageSquare className="mx-auto h-8 w-8 text-muted-foreground/30 mb-2" />
                  <p className="text-xs text-muted-foreground">
                    Ask {agentName} anything
                  </p>
                </div>
              </div>
            )}
            {messages.map((msg, idx) => {
              const isAssistantStreaming =
                isStreaming && idx === lastAssistantIdx && msg.role === "assistant";
              // Empty assistant slot before the first token arrives — let
              // the thinking indicator below carry the visual weight instead
              // of rendering a blank bubble.
              if (msg.role === "assistant" && !msg.content) {
                return null;
              }
              return (
                <div
                  key={msg.id}
                  className={cn(
                    "flex gap-2 chat-bubble-in",
                    msg.role === "user" ? "justify-end" : "justify-start"
                  )}
                >
                  <div
                    className={cn(
                      "max-w-[85%] rounded-lg px-3 py-2 text-xs leading-relaxed",
                      msg.role === "user"
                        ? "bg-primary text-primary-foreground rounded-tr-sm"
                        : "bg-card border border-border text-foreground rounded-tl-sm"
                    )}
                  >
                    {msg.role === "user" ? (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    ) : (
                      <div className="relative">
                        <MarkdownBody content={msg.content} size="xs" />
                        {isAssistantStreaming && (
                          <span className="chat-caret" aria-hidden="true" />
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {/* Thinking indicator — 3 bouncing dots inside an assistant-styled
                bubble so the transition from "thinking" to "answering" feels
                continuous. Only visible between/before LLM token streams; the
                hook clears `thinkingNode` on first token. */}
            {(thinkingNode || (isStreaming && lastAssistantIdx >= 0 && !messages[lastAssistantIdx]?.content)) && (
              <div className="flex justify-start chat-bubble-in">
                <div className="flex items-center gap-2 rounded-lg rounded-tl-sm border border-border bg-card px-3 py-2.5">
                  <div className="flex items-end gap-1">
                    <span className="chat-typing-dot h-1.5 w-1.5 rounded-full bg-primary" style={{ animationDelay: "0ms" }} />
                    <span className="chat-typing-dot h-1.5 w-1.5 rounded-full bg-primary" style={{ animationDelay: "160ms" }} />
                    <span className="chat-typing-dot h-1.5 w-1.5 rounded-full bg-primary" style={{ animationDelay: "320ms" }} />
                  </div>
                  <span className="text-[11px] text-muted-foreground">
                    {humanizeAgentNode(thinkingNode)}…
                  </span>
                </div>
              </div>
            )}
            {error && (
              <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {error}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="border-t border-border p-3">
            <div className="flex items-end gap-2 rounded-lg border border-border bg-card p-1.5">
              <textarea
                ref={inputRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={`Message ${agentName}...`}
                rows={1}
                className="flex-1 resize-none bg-transparent px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
              />
              {isStreaming ? (
                <button
                  onClick={stopStreaming}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-destructive text-destructive-foreground hover:bg-destructive/90"
                >
                  <Square className="h-3 w-3" />
                </button>
              ) : (
                <button
                  onClick={handleSubmit}
                  disabled={!inputValue.trim()}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  <Send className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

interface ThreadHistoryListProps {
  threads: ThreadSummary[];
  activeId: string | undefined;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  agentName: string;
}

function ThreadHistoryList({
  threads,
  activeId,
  onSelect,
  onNewChat,
  agentName,
}: ThreadHistoryListProps) {
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="border-b border-border px-3 py-2">
        <button
          onClick={onNewChat}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
        >
          <Plus className="h-3 w-3" />
          New chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {threads.length === 0 ? (
          <div className="flex h-full items-center justify-center px-4 text-center">
            <p className="text-xs text-muted-foreground">
              No chats with {agentName} yet. Start one!
            </p>
          </div>
        ) : (
          <ul className="space-y-1">
            {threads.map((t) => (
              <li key={t.id}>
                <button
                  onClick={() => onSelect(t.id)}
                  className={cn(
                    "flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                    t.id === activeId
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                  )}
                >
                  <span className="line-clamp-1 w-full font-medium">
                    {t.title?.trim() || "Untitled chat"}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    {formatThreadDate(t.updated_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function formatThreadDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) {
    return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
