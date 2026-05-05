"use client";

import { useEffect, useState } from "react";
import { Hash, Loader2, X } from "lucide-react";
import { slugifyChannelName } from "./utils";

interface NewChannelModalProps {
  open: boolean;
  onClose: () => void;
  /** Resolves to the created channel id when the API call succeeds. The
   *  parent uses that id to auto-select the channel after creation. */
  onCreate: (input: { name: string; description: string | null }) => Promise<void> | void;
}

/**
 * "+ New channel" modal. Mirrors the styling of NewTaskModal so the two
 * modals feel like the same family. The name field shows a live-slugified
 * preview so the user knows exactly what the channel handle will be — we
 * don't want to surprise them with "Marketing Ideas!" silently becoming
 * "marketing_ideas".
 */
export function NewChannelModal({ open, onClose, onCreate }: NewChannelModalProps) {
  const [rawName, setRawName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset state every time the modal closes — opening it again should be
  // a clean slate, not the previous attempt's leftovers.
  useEffect(() => {
    if (!open) {
      setRawName("");
      setDescription("");
      setSubmitting(false);
      setError(null);
    }
  }, [open]);

  if (!open) return null;

  const slug = slugifyChannelName(rawName);
  const canSubmit = slug.length > 0 && !submitting;

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        name: slug,
        description: description.trim() || null,
      });
    } catch (e) {
      setError((e as Error).message || "Failed to create channel");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">New channel</h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-foreground">
              Name <span className="text-destructive">*</span>
            </label>
            <div className="flex items-center rounded-md border border-border bg-background pl-3 pr-1 focus-within:border-primary/50">
              <Hash className="h-4 w-4 text-muted-foreground" />
              <input
                value={rawName}
                onChange={(e) => setRawName(e.target.value)}
                placeholder="marketing"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter" && canSubmit) handleSubmit();
                }}
                className="ml-2 flex-1 bg-transparent py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
              />
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Will become {" "}
              <code className="font-mono text-foreground">
                #{slug || "channel-name"}
              </code>{" "}
              — lowercase, underscores instead of spaces.
            </p>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-foreground">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Optional — what is this channel for?"
              className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none"
            />
          </div>

          {error && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {error}
            </div>
          )}
        </div>

        <div className="mt-5 flex gap-3">
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="flex flex-1 items-center justify-center gap-2 rounded-md bg-primary py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
            Create channel
          </button>
          <button
            onClick={onClose}
            disabled={submitting}
            className="flex-1 rounded-md border border-border py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
