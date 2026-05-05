"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  relativeTime,
  userDisplayName,
  userInitial,
} from "./utils";
import type { ChannelMessage, MentionableMaps } from "./types";

interface MessageRowProps {
  message: ChannelMessage;
  /** Lookup maps so we can resolve a reply's parent without a network call. */
  mentionable: MentionableMaps;
  /** The parent message when `in_reply_to_message_id` resolves locally. */
  replyTo: ChannelMessage | null;
}

/**
 * Render a single channel message — user OR agent. The visual contract is
 * the differentiator: agents get the Sparkles glyph + an "AI" tag so the
 * channel makes it instantly obvious which posts are autonomous. Mention
 * tokens (`@token`) inside the body get a primary-color treatment so the
 * "@strategist what should we make next?" line of work reads cleanly.
 */
export function MessageRow({ message, replyTo }: MessageRowProps) {
  const isAgent = !!message.sender_agent;
  const senderName = isAgent
    ? message.sender_agent!.name
    : message.sender_user
      ? userDisplayName(message.sender_user)
      : "Unknown";

  return (
    <div className="group flex gap-3 px-4 py-2.5 hover:bg-muted/20 transition-colors">
      {/* Avatar / agent badge */}
      <div
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-sm font-medium select-none",
          isAgent
            ? "bg-primary/15 border border-primary/25 text-primary"
            : "bg-muted text-foreground",
        )}
      >
        {isAgent ? (
          <Sparkles className="h-4 w-4" />
        ) : (
          message.sender_user ? userInitial(message.sender_user) : "?"
        )}
      </div>

      {/* Body */}
      <div className="min-w-0 flex-1">
        {replyTo && <ReplyAffordance parent={replyTo} />}

        <div className="flex items-baseline gap-2 leading-none">
          <span className="text-sm font-medium text-foreground truncate">
            {senderName}
          </span>
          {isAgent && (
            <span className="rounded-sm bg-primary/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-primary">
              AI
            </span>
          )}
          <span className="text-[11px] text-muted-foreground">
            {relativeTime(message.created_at)}
          </span>
          {message.edited_at && (
            <span className="text-[11px] text-muted-foreground/60">(edited)</span>
          )}
        </div>

        <div className="mt-1 text-sm text-foreground whitespace-pre-wrap break-words">
          <RenderedBody body={message.body} />
        </div>
      </div>
    </div>
  );
}

/**
 * Walk the message body emitting React nodes for two narrow inline
 * patterns:
 *   - `@token` — styled mention pill (no validation; backend already
 *     denormalized the canonical mention list onto the message).
 *   - `[text](href)` — a single-line markdown link, used by the agent
 *     dispatch fallback messages (e.g. "open the [Approvals page]
 *     (/app/approvals)"). Internal links go through `next/link` for
 *     client-side nav; external links open in a new tab.
 *
 * We deliberately do NOT do full markdown — the backend authors agent
 * fallback messages and we know exactly which tokens it emits, so a
 * scoped parser keeps the surface small.
 */
function RenderedBody({ body }: { body: string }) {
  // Combined alternation: link-first so a link inside the text doesn't
  // accidentally consume an `@` that belongs to a mention. Each branch
  // captures the bits we need to re-emit; the other branch's groups are
  // undefined when not matched.
  //   1: link text   2: link href   3: mention token (without @)
  const re = /\[([^\]]+)\]\(([^)\s]+)\)|@([A-Za-z0-9_-]+)/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = re.exec(body)) !== null) {
    if (match.index > lastIndex) {
      parts.push(body.slice(lastIndex, match.index));
    }
    if (match[1] !== undefined && match[2] !== undefined) {
      // Markdown link. Internal (`/...`) → next/link. External → <a>.
      const isInternal = match[2].startsWith("/");
      parts.push(
        isInternal ? (
          <Link
            key={`l-${key++}`}
            href={match[2]}
            className="underline text-primary hover:text-primary/80"
          >
            {match[1]}
          </Link>
        ) : (
          <a
            key={`l-${key++}`}
            href={match[2]}
            target="_blank"
            rel="noreferrer"
            className="underline text-primary hover:text-primary/80"
          >
            {match[1]}
          </a>
        ),
      );
    } else if (match[3] !== undefined) {
      parts.push(
        <span
          key={`m-${key++}`}
          className="rounded px-1 text-primary bg-primary/10 font-medium"
        >
          @{match[3]}
        </span>,
      );
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < body.length) parts.push(body.slice(lastIndex));
  return <>{parts}</>;
}

function ReplyAffordance({ parent }: { parent: ChannelMessage }) {
  const isAgent = !!parent.sender_agent;
  const name = isAgent
    ? parent.sender_agent!.name
    : parent.sender_user
      ? userDisplayName(parent.sender_user)
      : "Unknown";

  // Single-line preview, truncated. The actual reply target is in the
  // rendered list above us, so we don't need to be exhaustive — just
  // give enough so the reader knows what's being responded to.
  const preview = parent.body.length > 80
    ? parent.body.slice(0, 80) + "…"
    : parent.body;

  return (
    <div className="mb-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span className="text-muted-foreground/70">↳</span>
      <span className="font-medium text-muted-foreground">
        Replying to @{name}
      </span>
      <span className="truncate text-muted-foreground/70">— {preview}</span>
    </div>
  );
}
