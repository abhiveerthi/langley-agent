"use client";

import { useEffect } from "react";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { AgentThinking } from "./AgentThinking";
import { ApprovalCard } from "@/components/approvals/ApprovalCard";
import { useChat } from "@/hooks/useChat";

interface ChatWindowProps {
  threadId?: string;
  agentSlug?: string;
}

export function ChatWindow({ threadId, agentSlug }: ChatWindowProps) {
  const {
    messages,
    isStreaming,
    thinkingNode,
    error,
    pendingApproval,
    sendMessage,
    resumeApproval,
    stopStreaming,
    loadThread,
  } = useChat({ threadId, agentSlug });

  useEffect(() => {
    if (threadId) {
      loadThread(threadId);
    }
  }, [threadId, loadThread]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 && !pendingApproval ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <h2 className="text-lg font-medium text-foreground">
                Start a conversation
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Ask your AI agent anything
              </p>
            </div>
          </div>
        ) : (
          <MessageList messages={messages} />
        )}

        {/* Inline approval card — shows up when the agent's graph paused at
            an interrupt_before node. Approve/reject from here streams the
            continuation back into the same chat (no page-jump required). */}
        {pendingApproval && (
          <div className="mx-auto max-w-3xl px-4 pb-4">
            <ApprovalCard
              approval={pendingApproval}
              variant="inline"
              busy={isStreaming}
              onApprove={(id) => resumeApproval(id, "approved")}
              onReject={(id, fb) => resumeApproval(id, "rejected", fb)}
            />
          </div>
        )}

        {thinkingNode && <AgentThinking node={thinkingNode} />}
        {error && (
          <div className="mx-auto max-w-3xl px-4 py-2">
            <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          </div>
        )}
      </div>
      <ChatInput
        onSend={sendMessage}
        onStop={stopStreaming}
        isStreaming={isStreaming}
      />
    </div>
  );
}
