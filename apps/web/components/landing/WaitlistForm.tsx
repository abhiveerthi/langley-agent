"use client";

import { useState } from "react";
import { ArrowRight, Check, Loader2 } from "lucide-react";

type Status = "idle" | "submitting" | "success" | "error";

export function WaitlistForm({ size = "default" }: { size?: "default" | "large" }) {
  const [email, setEmail] = useState("");
  const [channelUrl, setChannelUrl] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string>("");

  const isLarge = size === "large";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (status === "submitting") return;

    setStatus("submitting");
    setErrorMessage("");

    try {
      const res = await fetch("/api/early-access", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, channel_url: channelUrl || null }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? "Something went wrong. Please try again.");
      }

      setStatus("success");
      setEmail("");
      setChannelUrl("");
    } catch (err) {
      setStatus("error");
      setErrorMessage(err instanceof Error ? err.message : "Unknown error");
    }
  }

  if (status === "success") {
    return (
      <div
        className={`flex items-start gap-3 rounded-lg border border-primary/30 bg-primary/5 p-4 ${
          isLarge ? "sm:p-5" : ""
        }`}
      >
        <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Check className="h-3.5 w-3.5" strokeWidth={3} />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground sm:text-base">
            You&apos;re on the list.
          </p>
          <p className="mt-1 text-xs text-muted-foreground sm:text-sm">
            We&apos;ll email when your seat opens up. If you dropped a channel URL,
            expect a free strategy report in your inbox soon.
          </p>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="w-full space-y-2.5 sm:space-y-3">
      <div className="flex flex-col gap-2.5 sm:flex-row sm:gap-2">
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@youtube.com"
          autoComplete="email"
          className={`w-full min-w-0 flex-1 rounded-md border border-border bg-input px-4 text-sm text-foreground placeholder:text-muted-foreground/60 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/30 ${
            isLarge ? "h-12 text-base" : "h-11"
          }`}
        />
        <button
          type="submit"
          disabled={status === "submitting"}
          className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60 ${
            isLarge ? "h-12 text-base" : "h-11"
          }`}
        >
          {status === "submitting" ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Joining
            </>
          ) : (
            <>
              Get early access
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
      </div>

      <input
        type="url"
        value={channelUrl}
        onChange={(e) => setChannelUrl(e.target.value)}
        placeholder="YouTube channel URL (optional — get a free strategy report)"
        autoComplete="url"
        className={`w-full rounded-md border border-border bg-input px-4 text-sm text-foreground placeholder:text-muted-foreground/60 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/30 ${
          isLarge ? "h-12" : "h-11"
        }`}
      />

      {status === "error" && (
        <p className="text-sm text-destructive">{errorMessage}</p>
      )}

      <p className="text-[11px] leading-relaxed text-muted-foreground sm:text-xs">
        No spam. We&apos;ll only email when your seat is ready.
      </p>
    </form>
  );
}
