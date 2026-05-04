"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Check,
  Copy,
  Loader2,
  Mail,
  MessagesSquare,
  Trash2,
  UserPlus,
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Member = {
  user_id: string;
  email: string;
  full_name: string | null;
  role: string;
  joined_at: string;
};

type Invite = {
  id: string;
  email: string;
  invited_by: string;
  delivery_method: "email" | "slack" | "both";
  slack_channel_id: string | null;
  // NOTE: `magic_link` is intentionally NOT on the list shape — it's
  // a single-use sign-in token bound to the invitee's email and would
  // let any org member impersonate any pending invitee if exposed in
  // a list endpoint. Fetch it on demand via /api/invites/{id}/link.
  last_delivery_attempt_at: string | null;
  last_delivery_error: string | null;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

type SlackChannel = {
  id: string;
  name: string;
  is_private: boolean;
  is_member: boolean;
};

type Toast = { kind: "ok" | "err"; text: string };

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

export default function TeamPage() {
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [slackInstalled, setSlackInstalled] = useState(false);
  const [slackChannels, setSlackChannels] = useState<SlackChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  // Invite form state
  const [inviteEmail, setInviteEmail] = useState("");
  const [deliveryMethod, setDeliveryMethod] = useState<"email" | "slack" | "both">("email");
  const [selectedChannel, setSelectedChannel] = useState<string>("");
  const [sending, setSending] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [copyingId, setCopyingId] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setError("Not signed in");
        setLoading(false);
        return;
      }
      const [membersR, invitesR, slackR] = await Promise.all([
        fetch(`${API}/api/members`, { headers: auth }),
        fetch(`${API}/api/invites`, { headers: auth }),
        fetch(`${API}/api/slack/channels`, { headers: auth }),
      ]);
      if (!membersR.ok) throw new Error(`members ${membersR.status}`);
      if (!invitesR.ok) throw new Error(`invites ${invitesR.status}`);
      const m: Member[] = await membersR.json();
      const inv: Invite[] = await invitesR.json();
      setMembers(m);
      setInvites(inv);
      if (slackR.ok) {
        const s = await slackR.json();
        setSlackInstalled(Boolean(s.installed));
        setSlackChannels(s.channels || []);
      }
    } catch (e) {
      setError((e as Error).message || "Failed to load team data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Auto-clear toast after a few seconds.
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const sendInvite = useCallback(async () => {
    const email = inviteEmail.trim().toLowerCase();
    if (!email) {
      setToast({ kind: "err", text: "Enter an email address" });
      return;
    }
    if ((deliveryMethod === "slack" || deliveryMethod === "both") && !selectedChannel) {
      setToast({ kind: "err", text: "Pick a Slack channel for the invite" });
      return;
    }
    setSending(true);
    try {
      const auth = await authHeader();
      const resp = await fetch(`${API}/api/invites`, {
        method: "POST",
        headers: { ...auth, "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          delivery_method: deliveryMethod,
          slack_channel_id:
            deliveryMethod === "slack" || deliveryMethod === "both" ? selectedChannel : null,
        }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        const detail = body?.detail || `HTTP ${resp.status}`;
        setToast({ kind: "err", text: detail });
        setSending(false);
        return;
      }
      const data = await resp.json();
      const warnings: string[] = data?.delivery_warnings || [];
      if (warnings.length > 0) {
        setToast({ kind: "err", text: `Sent with warnings: ${warnings.join("; ")}` });
      } else {
        setToast({ kind: "ok", text: `Invite sent to ${email}` });
      }
      setInviteEmail("");
      // Reload invites so the row appears.
      await loadAll();
    } catch (e) {
      setToast({ kind: "err", text: (e as Error).message || "Send failed" });
    } finally {
      setSending(false);
    }
  }, [inviteEmail, deliveryMethod, selectedChannel, loadAll]);

  const copyMagicLink = useCallback(async (inviteId: string) => {
    setCopyingId(inviteId);
    try {
      const auth = await authHeader();
      const resp = await fetch(`${API}/api/invites/${inviteId}/link`, { headers: auth });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        const detail = body?.detail || `HTTP ${resp.status}`;
        setToast({ kind: "err", text: detail });
        return;
      }
      const { magic_link } = await resp.json();
      if (!magic_link) {
        setToast({ kind: "err", text: "No link returned" });
        return;
      }
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(magic_link);
        setToast({ kind: "ok", text: "Magic link copied — paste it anywhere" });
      } else {
        window.prompt("Copy the magic link manually:", magic_link);
      }
    } catch (e) {
      setToast({ kind: "err", text: `Couldn't copy: ${(e as Error).message}` });
    } finally {
      setCopyingId(null);
    }
  }, []);

  const revokeInvite = useCallback(
    async (inviteId: string) => {
      setRevokingId(inviteId);
      try {
        const auth = await authHeader();
        const resp = await fetch(`${API}/api/invites/${inviteId}`, {
          method: "DELETE",
          headers: auth,
        });
        if (!resp.ok && resp.status !== 204) {
          const body = await resp.json().catch(() => ({}));
          setToast({ kind: "err", text: body?.detail || `HTTP ${resp.status}` });
          return;
        }
        setInvites((prev) => prev.filter((i) => i.id !== inviteId));
        setToast({ kind: "ok", text: "Invite revoked" });
      } catch (e) {
        setToast({ kind: "err", text: (e as Error).message || "Revoke failed" });
      } finally {
        setRevokingId(null);
      }
    },
    [],
  );

  const slackPickerVisible = deliveryMethod === "slack" || deliveryMethod === "both";

  return (
    <div className="mx-auto max-w-4xl space-y-8 p-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold">Team</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Invite teammates to your workspace. Invitees join with a limited role
          that doesn&apos;t show sponsor deals or brand profile data; everything
          else stays shared.
        </p>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-md border px-3 py-2 text-sm",
            toast.kind === "ok"
              ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700"
              : "border-rose-500/30 bg-rose-500/5 text-rose-700",
          )}
        >
          {toast.kind === "ok" ? (
            <Check className="h-4 w-4 shrink-0" />
          ) : (
            <AlertCircle className="h-4 w-4 shrink-0" />
          )}
          <span className="wrap-break-word">{toast.text}</span>
        </div>
      )}

      {/* Invite form */}
      <Section
        title="Invite a teammate"
        subtitle="Send via email, Slack, or both. They'll click the magic link and complete setup."
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_auto]">
          <input
            type="email"
            placeholder="alice@example.com"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
            disabled={sending}
            className="rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <button
            onClick={sendInvite}
            disabled={sending || !inviteEmail.trim()}
            className={cn(
              "flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors",
              sending || !inviteEmail.trim()
                ? "cursor-not-allowed bg-muted text-muted-foreground"
                : "bg-primary text-primary-foreground hover:bg-primary/90",
            )}
          >
            {sending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <UserPlus className="h-4 w-4" />
            )}
            {sending ? "Sending…" : "Send invite"}
          </button>
        </div>

        <div className="flex flex-wrap gap-2">
          <DeliveryToggle
            active={deliveryMethod === "email"}
            disabled={sending}
            onClick={() => setDeliveryMethod("email")}
            icon={<Mail className="h-3.5 w-3.5" />}
            label="Email"
          />
          <DeliveryToggle
            active={deliveryMethod === "slack"}
            disabled={sending || !slackInstalled}
            onClick={() => setDeliveryMethod("slack")}
            icon={<MessagesSquare className="h-3.5 w-3.5" />}
            label="Slack"
          />
          <DeliveryToggle
            active={deliveryMethod === "both"}
            disabled={sending || !slackInstalled}
            onClick={() => setDeliveryMethod("both")}
            icon={
              <span className="flex items-center gap-1">
                <Mail className="h-3 w-3" />
                <MessagesSquare className="h-3 w-3" />
              </span>
            }
            label="Both"
          />
          {!slackInstalled && (
            <span className="text-xs text-muted-foreground self-center ml-1">
              Slack not installed for this org
            </span>
          )}
        </div>

        {slackPickerVisible && slackInstalled && (
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-foreground">
              Slack channel for invite
            </label>
            <select
              value={selectedChannel}
              onChange={(e) => setSelectedChannel(e.target.value)}
              disabled={sending}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">Pick a channel…</option>
              {slackChannels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.is_private ? "🔒 " : "# "}
                  {c.name}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-muted-foreground">
              The bot must be a member of the channel. The invite link gets
              posted there as a message; Slack doesn&apos;t allow bot DMs.
            </p>
          </div>
        )}
      </Section>

      {/* Pending invites */}
      <Section
        title={`Pending invites${invites.length ? ` (${invites.length})` : ""}`}
        subtitle="Outstanding invites that haven't been accepted yet."
      >
        {loading ? (
          <Loader />
        ) : invites.length === 0 ? (
          <Empty text="No pending invites." />
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {invites.map((inv) => (
              <li key={inv.id} className="flex items-start justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-foreground">{inv.email}</div>
                  <div className="text-xs text-muted-foreground">
                    {humanDelivery(inv.delivery_method)} ·{" "}
                    {humanDate(inv.last_delivery_attempt_at || inv.created_at)}
                  </div>
                  {inv.last_delivery_error && (
                    <div className="mt-1 text-xs text-rose-600">
                      Delivery error: {inv.last_delivery_error}
                    </div>
                  )}
                  <div className="mt-1 text-[11px] text-muted-foreground/80">
                    Need to send manually? Use the Copy link button.
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    onClick={() => copyMagicLink(inv.id)}
                    disabled={copyingId === inv.id}
                    title="Fetch and copy the magic link to clipboard"
                    className="flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/5 hover:text-primary disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-card disabled:hover:text-muted-foreground"
                  >
                    {copyingId === inv.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Copy className="h-3 w-3" />
                    )}
                    Copy link
                  </button>
                  <button
                    onClick={() => revokeInvite(inv.id)}
                    disabled={revokingId === inv.id}
                    className="flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-rose-500/50 hover:bg-rose-500/5 hover:text-rose-700 disabled:opacity-50"
                  >
                    {revokingId === inv.id ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3" />
                    )}
                    Revoke
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Members */}
      <Section
        title={`Members${members.length ? ` (${members.length})` : ""}`}
        subtitle="People with active access to this workspace."
      >
        {loading ? (
          <Loader />
        ) : members.length === 0 ? (
          <Empty text="No members yet." />
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {members.map((m) => (
              <li key={m.user_id} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-foreground">
                    {m.full_name || m.email}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {m.full_name ? `${m.email} · ` : ""}joined {humanDate(m.joined_at)}
                  </div>
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                    m.role === "owner"
                      ? "border-primary/30 bg-primary/5 text-primary"
                      : m.role === "limited"
                        ? "border-border bg-muted text-muted-foreground"
                        : "border-border bg-background text-foreground",
                  )}
                >
                  {m.role}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-700">
          {error}
        </div>
      )}
    </div>
  );
}

// ── Subcomponents ─────────────────────────────────────────────────────────

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function DeliveryToggle({
  active,
  disabled,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
        active
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-border bg-card text-muted-foreground hover:bg-accent hover:text-foreground",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function Loader() {
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      Loading…
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
      {text}
    </div>
  );
}

function humanDate(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function humanDelivery(m: "email" | "slack" | "both"): string {
  if (m === "email") return "Sent via email";
  if (m === "slack") return "Posted to Slack";
  return "Sent via email + Slack";
}
