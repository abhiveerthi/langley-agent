"use client";

import { useState } from "react";
import { Check, Loader2, MessageCircle, Send, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Shape returned by the backend's `get_approval_request(state)` per agent —
 * see packages/agents/<agent>/agent.py. `action_type` discriminates which
 * fields show up in `payload`.
 */
export interface ApprovalRecord {
  id: string;
  org_id: string;
  thread_id: string | null;
  requested_by_agent: string;
  action_type: string;
  action_payload: Record<string, unknown>;
  preview: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
}

interface ApprovalCardProps {
  /**
   * Either a full DB row (from `GET /api/approvals` for the list page) OR
   * the inline-pending shape from the SSE `waiting_approval` event. The two
   * differ only in field names — both go through `normalize` below.
   */
  approval: ApprovalRecord | InlinePending;
  /** Called when user clicks Approve. Should fire the resume request. */
  onApprove: (approvalId: string) => Promise<void> | void;
  /** Called when user clicks Reject (with optional feedback string). */
  onReject: (approvalId: string, feedback: string) => Promise<void> | void;
  /** Streaming state — disables buttons while a previous resume is mid-flight. */
  busy?: boolean;
  /** Compact = inline-in-chat; expanded = standalone approvals list. */
  variant?: "inline" | "list";
}

interface InlinePending {
  approval_id: string;
  thread_id: string;
  agent_slug: string;
  action_type: string;
  preview: string;
  payload: Record<string, unknown>;
}

function normalize(input: ApprovalCardProps["approval"]) {
  // The list endpoint returns DB rows (id / requested_by_agent / action_payload),
  // the SSE event sends a slightly different shape (approval_id / agent_slug /
  // payload). Smooth both into one object the card body can render.
  if ("approval_id" in input) {
    return {
      id: input.approval_id,
      agent_slug: input.agent_slug,
      action_type: input.action_type,
      payload: input.payload,
      preview: input.preview,
    };
  }
  return {
    id: input.id,
    agent_slug: input.requested_by_agent,
    action_type: input.action_type,
    payload: input.action_payload,
    preview: input.preview,
  };
}

const AGENT_LABELS: Record<string, string> = {
  "brand-manager": "Brand Manager",
  "community-manager": "Community Manager",
  publisher: "Publisher",
  strategist: "Strategist",
};

export function ApprovalCard({
  approval,
  onApprove,
  onReject,
  busy = false,
  variant = "list",
}: ApprovalCardProps) {
  const norm = normalize(approval);
  const [feedback, setFeedback] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [localBusy, setLocalBusy] = useState(false);

  const disabled = busy || localBusy;

  const agentLabel = AGENT_LABELS[norm.agent_slug] ?? norm.agent_slug;

  async function handleApprove() {
    setLocalBusy(true);
    try {
      await onApprove(norm.id);
    } finally {
      setLocalBusy(false);
    }
  }

  async function handleReject() {
    setLocalBusy(true);
    try {
      await onReject(norm.id, feedback.trim());
      setShowRejectForm(false);
      setFeedback("");
    } finally {
      setLocalBusy(false);
    }
  }

  return (
    <div
      className={cn(
        "rounded-lg border bg-card",
        variant === "inline"
          ? "border-amber-500/30 bg-amber-500/5 p-4"
          : "border-border p-5"
      )}
    >
      {/* Header */}
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                "bg-amber-500/15 text-amber-400"
              )}
            >
              Awaiting approval
            </span>
            <span className="text-xs text-muted-foreground">
              {agentLabel} &middot; {norm.action_type.replace(/_/g, " ")}
            </span>
          </div>
          <p className="mt-2 text-sm font-medium text-foreground">{norm.preview}</p>
        </div>
      </div>

      {/* Action-type-specific body */}
      <ApprovalBody actionType={norm.action_type} payload={norm.payload} />

      {/* Buttons / reject form */}
      {showRejectForm ? (
        <div className="mt-4 space-y-2">
          <label className="text-xs font-medium text-foreground">
            Feedback (what should the agent change?)
          </label>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="e.g. make it shorter, less salesy, mention our new optic line"
            rows={3}
            className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none"
          />
          <div className="flex gap-2">
            <button
              onClick={handleReject}
              disabled={disabled}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-destructive px-3 py-2 text-xs font-medium text-destructive-foreground transition-colors hover:bg-destructive/90 disabled:opacity-50"
            >
              {localBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              Send feedback &amp; revise
            </button>
            <button
              onClick={() => {
                setShowRejectForm(false);
                setFeedback("");
              }}
              disabled={disabled}
              className="rounded-md border border-border px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex gap-2">
          <button
            onClick={handleApprove}
            disabled={disabled}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            {localBusy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            Approve &amp; send
          </button>
          <button
            onClick={() => setShowRejectForm(true)}
            disabled={disabled}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
          >
            <X className="h-3.5 w-3.5" />
            Reject &amp; revise
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Action-type-aware body. Brand Manager pitches show recipient/subject/body;
 * Community Manager replies show the original comment + the proposed reply.
 * Anything we don't recognize falls back to a generic JSON dump so unknown
 * agents don't render blank.
 */
function ApprovalBody({
  actionType,
  payload,
}: {
  actionType: string;
  payload: Record<string, unknown>;
}) {
  if (actionType === "send_email") {
    const recipient = (payload.recipient as string) || "(no recipient)";
    const subject = (payload.subject as string) || "(no subject)";
    const body = (payload.body as string) || (payload.draft as string) || "";
    return (
      <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3 text-xs">
        <Field label="To" value={recipient} />
        <Field label="Subject" value={subject} />
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Body
          </p>
          <pre className="mt-1 whitespace-pre-wrap break-words font-sans text-xs text-foreground">
            {body}
          </pre>
        </div>
      </div>
    );
  }

  if (actionType === "reply_comment") {
    const author = (payload.parent_author as string) || "(unknown)";
    const videoTitle = (payload.parent_video_title as string) || "";
    const original = (payload.parent_comment_text as string) || "";
    const reply = (payload.reply_draft as string) || "";
    return (
      <div className="space-y-3">
        <div className="rounded-md border border-border bg-muted/30 p-3 text-xs">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            <MessageCircle className="h-3 w-3" />
            <span>{author}</span>
            {videoTitle && (
              <span className="text-muted-foreground/60">on &ldquo;{videoTitle}&rdquo;</span>
            )}
          </div>
          <p className="text-foreground">{original}</p>
        </div>
        <div className="rounded-md border border-primary/30 bg-primary/5 p-3 text-xs">
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-primary">
            Proposed reply
          </p>
          <p className="text-foreground">{reply}</p>
        </div>
      </div>
    );
  }

  // Generic fallback — keeps unknown agents renderable while being honest
  // about not having a tailored UI for them yet.
  return (
    <pre className="overflow-x-auto rounded-md border border-border bg-muted/30 p-3 text-[11px] text-muted-foreground">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <span className="w-16 shrink-0 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className="break-all text-foreground">{value}</span>
    </div>
  );
}
