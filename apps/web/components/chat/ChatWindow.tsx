"use client";

import { useCallback, useEffect } from "react";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
import { AgentThinking } from "./AgentThinking";
import { ApprovalCard } from "@/components/approvals/ApprovalCard";
import { useChat } from "@/hooks/useChat";

interface ChatWindowProps {
  threadId?: string;
  agentSlug?: string;
}

// Lightweight intent detection for natural-language approve/reject when an
// inline approval card is showing. Users who don't notice the card and just
// type "approved" / "send it" / "no rewrite that" otherwise get stuck — the
// chat reply spawns a fresh graph run that has no idea about the pending HITL.
const APPROVE_PATTERN =
  /^\s*(approve(d)?|approved!?|yes(,?\s*(send|post|go|ship|do it))?|send( it)?( now)?|post( it)?|ship it|go( ahead)?|do it|looks good|lgtm|👍|✅|sure( send)?)\s*[.!?]?\s*$/i;
// Reject = ask the agent to revise. The user supplies feedback in chat.
const REJECT_PATTERN =
  /^\s*(reject(ed)?|reject it|redo( it)?|rewrite|try again|revise)\s*[.!?]?\s*$/i;
// Cancel = throw the draft away entirely. Different from reject — no revise.
const CANCEL_PATTERN =
  /^\s*(cancel|discard( it)?|throw (it )?away|delete( it)?|nevermind|never mind|forget it|drop it|abort|nope|no)\s*[.!?]?\s*$/i;

export function ChatWindow({ threadId, agentSlug }: ChatWindowProps) {
  const {
    messages,
    isStreaming,
    thinkingNode,
    error,
    pendingApproval,
    sendMessage,
    resumeApproval,
    cancelApproval,
    stopStreaming,
    loadThread,
  } = useChat({ threadId, agentSlug });

  // If a draft is awaiting approval and the user types an approve/reject
  // intent in chat, resolve the approval directly instead of starting a new
  // run. Anything that doesn't pattern-match (e.g. "make it shorter") still
  // falls through to sendMessage, which is fine — the agent can rewrite.
  const handleSend = useCallback(
    (text: string) => {
      if (pendingApproval) {
        if (APPROVE_PATTERN.test(text)) {
          resumeApproval(pendingApproval.approval_id, "approved");
          return;
        }
        if (CANCEL_PATTERN.test(text)) {
          cancelApproval(pendingApproval.approval_id);
          return;
        }
        if (REJECT_PATTERN.test(text)) {
          resumeApproval(pendingApproval.approval_id, "rejected");
          return;
        }
      }
      sendMessage(text);
    },
    [pendingApproval, resumeApproval, cancelApproval, sendMessage]
  );

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
          <MessageList messages={messages} isStreaming={isStreaming} />
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
              onCancel={(id) => cancelApproval(id)}
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
        onSend={handleSend}
        onStop={stopStreaming}
        isStreaming={isStreaming}
      />
    </div>
  );
}
