"use client";

import {
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Loader2, Send, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { userDisplayName, userMentionToken } from "./utils";
import type { MentionableMaps, MentionableAgent, MentionableUser } from "./types";

interface MessageComposerProps {
  channelName: string;
  mentionable: MentionableMaps;
  /** Submit hook; resolves to the inserted Message id (used to dedupe the
   *  realtime echo) or throws on failure so we can keep the draft. */
  onSend: (body: string) => Promise<string | null>;
  disabled?: boolean;
}

type Suggestion =
  | { kind: "agent"; item: MentionableAgent }
  | { kind: "user"; item: MentionableUser };

/**
 * The composer is intentionally small but does a few finicky things:
 *
 *   1. Autosizes the textarea between 1 and 6 rows by tracking scrollHeight
 *      after every keystroke. Pure CSS can't pull this off because we need
 *      a max-height clamp.
 *   2. Submits on Enter, allows Shift+Enter for newline. The same "Enter
 *      submits" rule is suppressed while the mention popover is open so the
 *      first Enter selects a suggestion instead of sending.
 *   3. Detects an in-progress `@token` only when it's at the start of input
 *      or follows whitespace (so emails like a@b.com don't trigger the
 *      popover mid-message).
 *   4. Keyboard navigation: ArrowUp/Down move the highlighted suggestion,
 *      Enter selects, Escape closes. The popover ranks agents above users
 *      because they're the high-value mention type for this product.
 */
export function MessageComposer({
  channelName,
  mentionable,
  onSend,
  disabled = false,
}: MessageComposerProps) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Mention popover state.
  const [mentionState, setMentionState] = useState<{
    /** The "@foo" partial — without the `@`. */
    query: string;
    /** Caret offset where the `@` sits (so we can replace cleanly). */
    atIndex: number;
    /** Highlighted item in the suggestion list. */
    cursor: number;
  } | null>(null);

  // Reset draft + state when the channel switches.
  useEffect(() => {
    setDraft("");
    setMentionState(null);
    setError(null);
    setBusy(false);
  }, [channelName]);

  // Autosize the textarea to its content (capped at ~6 rows). We reset to
  // auto first so shrinking on backspace works.
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const lineHeight = 20; // matches text-sm leading
    const max = lineHeight * 6 + 16; // plus padding
    ta.style.height = `${Math.min(ta.scrollHeight, max)}px`;
  }, [draft]);

  // Build the active suggestion list from the mention query.
  const suggestions: Suggestion[] = useMemo(() => {
    if (!mentionState) return [];
    const q = mentionState.query.toLowerCase();
    const matchedAgents = mentionable.agents.filter(
      (a) =>
        a.slug.toLowerCase().includes(q) ||
        a.name.toLowerCase().includes(q),
    );
    const matchedUsers = mentionable.users.filter((u) => {
      const name = (u.full_name || u.email).toLowerCase();
      return name.includes(q);
    });
    return [
      ...matchedAgents.map<Suggestion>((item) => ({ kind: "agent", item })),
      ...matchedUsers.map<Suggestion>((item) => ({ kind: "user", item })),
    ].slice(0, 8);
  }, [mentionState, mentionable]);

  const updateMentionContext = useCallback((value: string, caret: number) => {
    // Walk backwards from the caret looking for either an `@` (mention
    // start) or a whitespace/start-of-string (no-mention boundary).
    let i = caret - 1;
    while (i >= 0) {
      const ch = value[i];
      if (ch === "@") {
        // The `@` must be at the start or right after whitespace to count
        // as a mention. This stops "user@example.com" from popping the
        // suggestion popover mid-email.
        const before = i === 0 ? "" : value[i - 1];
        if (i === 0 || /\s/.test(before)) {
          const query = value.slice(i + 1, caret);
          // Mention tokens only contain [a-z0-9_-]. If a space (or any
          // disallowed char) was typed, we close the popover.
          if (/^[A-Za-z0-9_-]*$/.test(query)) {
            setMentionState((prev) => ({
              query,
              atIndex: i,
              cursor: prev && prev.atIndex === i ? Math.min(prev.cursor, 99) : 0,
            }));
            return;
          }
        }
        setMentionState(null);
        return;
      }
      if (/\s/.test(ch)) {
        setMentionState(null);
        return;
      }
      i--;
    }
    setMentionState(null);
  }, []);

  // Reclamp the cursor when the suggestion list shrinks (e.g. user keeps
  // typing and only one match is left). Otherwise the highlighted index
  // could point past the end.
  useEffect(() => {
    if (!mentionState) return;
    if (mentionState.cursor >= suggestions.length && suggestions.length > 0) {
      setMentionState({ ...mentionState, cursor: suggestions.length - 1 });
    }
  }, [suggestions.length, mentionState]);

  function selectSuggestion(idx: number) {
    if (!mentionState) return;
    const sug = suggestions[idx];
    if (!sug) return;
    const token =
      sug.kind === "agent"
        ? sug.item.slug
        : userMentionToken(sug.item);
    const before = draft.slice(0, mentionState.atIndex);
    const after = draft.slice(
      mentionState.atIndex + 1 + mentionState.query.length,
    );
    // Trailing space so the user can keep typing the rest of the message
    // without manually inserting one.
    const replacement = `@${token} `;
    const next = before + replacement + after;
    setDraft(next);
    setMentionState(null);
    // Restore focus + place caret right after the inserted token.
    queueMicrotask(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      const caret = before.length + replacement.length;
      ta.focus();
      ta.setSelectionRange(caret, caret);
    });
  }

  async function submit() {
    const body = draft.trim();
    if (!body || busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      await onSend(body);
      setDraft("");
      setMentionState(null);
    } catch (e) {
      setError((e as Error).message || "Failed to send");
    } finally {
      setBusy(false);
      // Re-focus so the user can keep typing without grabbing the mouse.
      queueMicrotask(() => textareaRef.current?.focus());
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Mention popover hotkeys take priority while it's open.
    if (mentionState && suggestions.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMentionState({
          ...mentionState,
          cursor: (mentionState.cursor + 1) % suggestions.length,
        });
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMentionState({
          ...mentionState,
          cursor:
            (mentionState.cursor - 1 + suggestions.length) % suggestions.length,
        });
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        selectSuggestion(mentionState.cursor);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMentionState(null);
        return;
      }
    }
    // Plain Enter submits, Shift+Enter newlines.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  function onChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const value = e.target.value;
    setDraft(value);
    // Compute mention context against the post-change caret position.
    const caret = e.target.selectionStart ?? value.length;
    updateMentionContext(value, caret);
  }

  return (
    <div className="border-t border-border bg-card/50 px-4 py-3 relative">
      {error && (
        <div className="mb-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
          {error}
        </div>
      )}

      {mentionState && suggestions.length > 0 && (
        <SuggestionPopover
          suggestions={suggestions}
          cursor={mentionState.cursor}
          onPick={(idx) => selectSuggestion(idx)}
          onHover={(idx) =>
            setMentionState((prev) =>
              prev ? { ...prev, cursor: idx } : prev,
            )
          }
        />
      )}

      <div className="flex items-end gap-2 rounded-lg border border-border bg-background px-3 py-2 focus-within:border-primary/40 transition-colors">
        <textarea
          ref={textareaRef}
          value={draft}
          onChange={onChange}
          onKeyDown={onKeyDown}
          onSelect={(e) => {
            const ta = e.currentTarget;
            updateMentionContext(ta.value, ta.selectionStart ?? ta.value.length);
          }}
          rows={1}
          disabled={disabled || busy}
          placeholder={`Message #${channelName}…`}
          className="flex-1 resize-none bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
        />
        <button
          type="button"
          onClick={submit}
          disabled={!draft.trim() || disabled || busy}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          aria-label="Send"
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Send className="h-3.5 w-3.5" />
          )}
        </button>
      </div>
      <div className="mt-1.5 text-[11px] text-muted-foreground">
        Enter to send · Shift+Enter for newline · @ to mention
      </div>
    </div>
  );
}

function SuggestionPopover({
  suggestions,
  cursor,
  onPick,
  onHover,
}: {
  suggestions: Suggestion[];
  cursor: number;
  onPick: (idx: number) => void;
  onHover: (idx: number) => void;
}) {
  // Group for a Slack-style "Agents" + "People" split. We preserve the
  // global cursor index so keyboard nav still works across the split.
  const agentEntries: { sug: Suggestion; index: number }[] = [];
  const userEntries: { sug: Suggestion; index: number }[] = [];
  suggestions.forEach((sug, index) => {
    if (sug.kind === "agent") agentEntries.push({ sug, index });
    else userEntries.push({ sug, index });
  });

  return (
    <div className="absolute bottom-full left-4 right-4 mb-2 rounded-lg border border-border bg-card shadow-xl overflow-hidden">
      {agentEntries.length > 0 && (
        <div>
          <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Agents
          </div>
          {agentEntries.map(({ sug, index }) =>
            sug.kind === "agent" ? (
              <SuggestionItem
                key={`a-${sug.item.slug}`}
                active={index === cursor}
                onClick={() => onPick(index)}
                onMouseEnter={() => onHover(index)}
                primary={sug.item.name}
                secondary={`@${sug.item.slug}`}
                kind="agent"
              />
            ) : null,
          )}
        </div>
      )}
      {userEntries.length > 0 && (
        <div>
          <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            People
          </div>
          {userEntries.map(({ sug, index }) =>
            sug.kind === "user" ? (
              <SuggestionItem
                key={`u-${sug.item.id}`}
                active={index === cursor}
                onClick={() => onPick(index)}
                onMouseEnter={() => onHover(index)}
                primary={userDisplayName(sug.item)}
                secondary={sug.item.email}
                kind="user"
              />
            ) : null,
          )}
        </div>
      )}
    </div>
  );
}

function SuggestionItem({
  active,
  primary,
  secondary,
  kind,
  onClick,
  onMouseEnter,
}: {
  active: boolean;
  primary: string;
  secondary: string;
  kind: "agent" | "user";
  onClick: () => void;
  onMouseEnter: () => void;
}) {
  return (
    <button
      type="button"
      // mousedown rather than click — click fires after blur, which would
      // close the popover before the selection could land.
      onMouseDown={(e) => {
        e.preventDefault();
        onClick();
      }}
      onMouseEnter={onMouseEnter}
      className={cn(
        "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors",
        active ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/60",
      )}
    >
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-semibold",
          kind === "agent"
            ? "bg-primary/15 text-primary"
            : "bg-muted text-foreground",
        )}
      >
        {kind === "agent" ? <Sparkles className="h-3 w-3" /> : primary[0]?.toUpperCase() || "?"}
      </span>
      <span className="text-foreground truncate">{primary}</span>
      <span className="ml-auto text-[11px] text-muted-foreground/70 truncate">
        {secondary}
      </span>
    </button>
  );
}
