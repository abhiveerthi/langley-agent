"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  Sparkles,
  Loader2,
  AlertCircle,
  Check,
  Plus,
  X,
  Image as ImageIcon,
  Megaphone,
  Compass,
  MessageCircle,
  Briefcase,
} from "lucide-react";
import { cn } from "@/lib/utils";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type BrandShape = {
  name: string | null;
  voice: string | null;
  primary_email: string | null;
  logo_url: string | null;
  tagline: string | null;
  about: string | null;
  writing_sample: string | null;
  tone_keywords: string[];
  avoid_list: string[];
  default_cta: string | null;
  audience_descriptor: string | null;
};

type ProfileResp = {
  brand: BrandShape;
  niche_slug: string | null;
  audience_size: string | null;
  youtube_channel_id: string | null;
};

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; data: ProfileResp };

const EMPTY_BRAND: BrandShape = {
  name: "",
  voice: "",
  primary_email: "",
  logo_url: "",
  tagline: "",
  about: "",
  writing_sample: "",
  tone_keywords: [],
  avoid_list: [],
  default_cta: "",
  audience_descriptor: "",
};

async function authHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

export default function BrandProfilePage() {
  const [load, setLoad] = useState<LoadState>({ kind: "loading" });
  const [draft, setDraft] = useState<BrandShape>(EMPTY_BRAND);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const fetchProfile = useCallback(async () => {
    setLoad({ kind: "loading" });
    try {
      const auth = await authHeader();
      if (!auth.Authorization) {
        setLoad({ kind: "error", message: "Not signed in" });
        return;
      }
      const res = await fetch(`${API}/api/profile`, { headers: auth });
      if (!res.ok) {
        setLoad({ kind: "error", message: `HTTP ${res.status}` });
        return;
      }
      const data = (await res.json()) as ProfileResp;
      setLoad({ kind: "ok", data });
      setDraft({
        name: data.brand.name ?? "",
        voice: data.brand.voice ?? "",
        primary_email: data.brand.primary_email ?? "",
        logo_url: data.brand.logo_url ?? "",
        tagline: data.brand.tagline ?? "",
        about: data.brand.about ?? "",
        writing_sample: data.brand.writing_sample ?? "",
        tone_keywords: data.brand.tone_keywords ?? [],
        avoid_list: data.brand.avoid_list ?? [],
        default_cta: data.brand.default_cta ?? "",
        audience_descriptor: data.brand.audience_descriptor ?? "",
      });
    } catch (e) {
      setLoad({ kind: "error", message: (e as Error).message });
    }
  }, []);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  const isDirty = useMemo(() => {
    if (load.kind !== "ok") return false;
    const orig = load.data.brand;
    const same =
      (orig.name ?? "") === (draft.name ?? "") &&
      (orig.voice ?? "") === (draft.voice ?? "") &&
      (orig.primary_email ?? "") === (draft.primary_email ?? "") &&
      (orig.logo_url ?? "") === (draft.logo_url ?? "") &&
      (orig.tagline ?? "") === (draft.tagline ?? "") &&
      (orig.about ?? "") === (draft.about ?? "") &&
      (orig.writing_sample ?? "") === (draft.writing_sample ?? "") &&
      (orig.default_cta ?? "") === (draft.default_cta ?? "") &&
      (orig.audience_descriptor ?? "") === (draft.audience_descriptor ?? "") &&
      arrEq(orig.tone_keywords ?? [], draft.tone_keywords) &&
      arrEq(orig.avoid_list ?? [], draft.avoid_list);
    return !same;
  }, [load, draft]);

  async function save() {
    if (saving || !isDirty) return;
    setSaving(true);
    try {
      const auth = await authHeader();
      const body = {
        brand_name: emptyToNull(draft.name),
        brand_voice: emptyToNull(draft.voice),
        brand_primary_email: emptyToNull(draft.primary_email),
        brand_logo_url: emptyToNull(draft.logo_url),
        brand_tagline: emptyToNull(draft.tagline),
        brand_about: emptyToNull(draft.about),
        brand_writing_sample: emptyToNull(draft.writing_sample),
        brand_tone_keywords: draft.tone_keywords,
        brand_avoid_list: draft.avoid_list,
        brand_default_cta: emptyToNull(draft.default_cta),
        brand_audience_descriptor: emptyToNull(draft.audience_descriptor),
      };
      const res = await fetch(`${API}/api/profile`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...auth },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ProfileResp;
      setLoad({ kind: "ok", data });
      setToast({ kind: "ok", text: "Brand profile saved" });
    } catch (e) {
      setToast({ kind: "err", text: `Save failed: ${(e as Error).message}` });
    } finally {
      setSaving(false);
    }
  }

  function reset() {
    if (load.kind !== "ok") return;
    const orig = load.data.brand;
    setDraft({
      name: orig.name ?? "",
      voice: orig.voice ?? "",
      primary_email: orig.primary_email ?? "",
      logo_url: orig.logo_url ?? "",
      tagline: orig.tagline ?? "",
      about: orig.about ?? "",
      writing_sample: orig.writing_sample ?? "",
      tone_keywords: orig.tone_keywords ?? [],
      avoid_list: orig.avoid_list ?? [],
      default_cta: orig.default_cta ?? "",
      audience_descriptor: orig.audience_descriptor ?? "",
    });
  }

  if (load.kind === "loading") {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading brand profile…
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4">
        <div className="flex items-center gap-2 mb-1">
          <AlertCircle className="h-4 w-4 text-red-400" />
          <span className="text-sm font-medium text-red-400">Couldn&apos;t load profile</span>
        </div>
        <div className="text-xs text-muted-foreground">{load.message}</div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-8 pb-24">
      {/* Header */}
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 border border-primary/20">
          <Sparkles className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">Brand Profile</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            What every agent reads before drafting. The more you fill in, the more the output sounds like you.
          </p>
        </div>
      </div>

      {/* Used-by row */}
      <div className="rounded-lg border border-border bg-muted/20 p-3 flex items-center gap-3 text-xs text-muted-foreground">
        <span className="text-foreground/70 font-medium">Read by:</span>
        <UsedByPill icon={Compass} label="Strategist" />
        <UsedByPill icon={Megaphone} label="Publisher" />
        <UsedByPill icon={MessageCircle} label="Community Manager" />
        <UsedByPill icon={Briefcase} label="Brand Manager" />
      </div>

      {/* Identity */}
      <Section title="Identity" subtitle="Who you are and what you make.">
        <Field label="Brand name" hint="Used in every system prompt as the org you're working for.">
          <input
            value={draft.name ?? ""}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            placeholder="e.g. Acme Studios"
            className={inputCls}
          />
        </Field>
        <Field label="Tagline" hint="One short line — your positioning. Quoted in pitches and thumbnail copy.">
          <input
            value={draft.tagline ?? ""}
            onChange={(e) => setDraft({ ...draft, tagline: e.target.value })}
            placeholder="e.g. Practical builds for working creators"
            className={inputCls}
          />
        </Field>
        <Field label="About" hint="Short company description. Available to every agent for context.">
          <textarea
            value={draft.about ?? ""}
            onChange={(e) => setDraft({ ...draft, about: e.target.value })}
            placeholder="What you make, who it's for, why it matters."
            rows={3}
            className={textareaCls}
          />
        </Field>
        <Field label="Logo URL" hint="Paste a URL for now — direct upload is coming.">
          <div className="flex items-center gap-3">
            {draft.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={draft.logo_url} alt="" className="h-12 w-12 rounded-md border border-border bg-muted object-cover" />
            ) : (
              <div className="flex h-12 w-12 items-center justify-center rounded-md border border-dashed border-border bg-muted/30">
                <ImageIcon className="h-4 w-4 text-muted-foreground" />
              </div>
            )}
            <input
              value={draft.logo_url ?? ""}
              onChange={(e) => setDraft({ ...draft, logo_url: e.target.value })}
              placeholder="https://…/logo.png"
              className={cn(inputCls, "flex-1")}
            />
          </div>
        </Field>
        <Field label="Primary email" hint="Used in pitch headers and as the reply-to on outbound mail.">
          <input
            value={draft.primary_email ?? ""}
            onChange={(e) => setDraft({ ...draft, primary_email: e.target.value })}
            placeholder="hello@yourbrand.com"
            className={inputCls}
          />
        </Field>
        <Field label="Audience" hint="Who you're talking to. Overrides the niche preset's default.">
          <input
            value={draft.audience_descriptor ?? ""}
            onChange={(e) => setDraft({ ...draft, audience_descriptor: e.target.value })}
            placeholder="e.g. mid-career creators with 10k–100k subs"
            className={inputCls}
          />
        </Field>
      </Section>

      {/* Voice */}
      <Section title="Voice" subtitle="The strongest single signal is a real writing sample.">
        <Field label="Voice description" hint="A few words on how you write. Threaded into every drafting prompt.">
          <input
            value={draft.voice ?? ""}
            onChange={(e) => setDraft({ ...draft, voice: e.target.value })}
            placeholder="e.g. direct, no fluff, uses second-person"
            className={inputCls}
          />
        </Field>
        <Field label="Tone keywords" hint="A handful of adjectives. Used as a quick steer when a longer description is overkill.">
          <ChipInput
            values={draft.tone_keywords}
            onChange={(v) => setDraft({ ...draft, tone_keywords: v })}
            placeholder="e.g. punchy, irreverent, no-fluff"
          />
        </Field>
        <Field label="Writing sample" hint="1–3 short paragraphs in your real voice. The agents pattern-match this when drafting.">
          <textarea
            value={draft.writing_sample ?? ""}
            onChange={(e) => setDraft({ ...draft, writing_sample: e.target.value })}
            placeholder="Drop a few sentences from a recent video description, tweet, or newsletter you wrote."
            rows={5}
            className={textareaCls}
          />
        </Field>
      </Section>

      {/* Guardrails */}
      <Section title="Guardrails" subtitle="What to avoid, and a default CTA when one is needed.">
        <Field label="Never use these phrases" hint="The agents will skip these in drafts. Add anything that screams AI or doesn't sound like you.">
          <ChipInput
            values={draft.avoid_list}
            onChange={(v) => setDraft({ ...draft, avoid_list: v })}
            placeholder="e.g. unlock synergy, game-changer, dive in"
          />
        </Field>
        <Field label="Default CTA" hint="When a piece needs a call to action and the user hasn't specified one.">
          <input
            value={draft.default_cta ?? ""}
            onChange={(e) => setDraft({ ...draft, default_cta: e.target.value })}
            placeholder="e.g. Subscribe for one practical build a week"
            className={inputCls}
          />
        </Field>
      </Section>

      {/* Save bar */}
      <div className="fixed bottom-6 right-6 z-40 flex items-center gap-3">
        {toast && (
          <span
            className={cn(
              "rounded-md border px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 backdrop-blur",
              toast.kind === "ok"
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                : "border-red-500/30 bg-red-500/10 text-red-400",
            )}
          >
            {toast.kind === "ok" ? <Check className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
            {toast.text}
          </span>
        )}
        {isDirty && (
          <button
            onClick={reset}
            disabled={saving}
            className="rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors disabled:opacity-60"
          >
            Discard
          </button>
        )}
        <button
          onClick={save}
          disabled={!isDirty || saving}
          className={cn(
            "rounded-md px-4 py-2 text-sm font-medium shadow-sm transition-colors flex items-center gap-2",
            isDirty
              ? "bg-primary text-primary-foreground hover:bg-primary/90"
              : "bg-muted text-muted-foreground cursor-not-allowed",
          )}
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          {saving ? "Saving…" : isDirty ? "Save changes" : "Saved"}
        </button>
      </div>
    </div>
  );
}

// ── Subcomponents ─────────────────────────────────────────────────────────

const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus:outline-none focus:ring-1 focus:ring-primary";
const textareaCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus:outline-none focus:ring-1 focus:ring-primary resize-y";

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        {subtitle && <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>}
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs font-medium text-foreground">{label}</label>
      {hint && <p className="text-[11px] text-muted-foreground mt-0.5 mb-2 leading-relaxed">{hint}</p>}
      {!hint && <div className="mb-2" />}
      {children}
    </div>
  );
}

function ChipInput({
  values,
  onChange,
  placeholder,
}: {
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const [pending, setPending] = useState("");

  function commit() {
    const v = pending.trim();
    if (!v) return;
    if (values.includes(v)) {
      setPending("");
      return;
    }
    onChange([...values, v]);
    setPending("");
  }

  function remove(idx: number) {
    onChange(values.filter((_, i) => i !== idx));
  }

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {values.map((v, i) => (
          <span
            key={`${v}-${i}`}
            className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-0.5 text-xs text-primary"
          >
            {v}
            <button
              type="button"
              onClick={() => remove(i)}
              className="text-primary/60 hover:text-primary"
              aria-label={`Remove ${v}`}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        {values.length === 0 && (
          <span className="text-[11px] text-muted-foreground italic">None set</span>
        )}
      </div>
      <div className="flex gap-2">
        <input
          value={pending}
          onChange={(e) => setPending(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              commit();
            }
            if (e.key === "Backspace" && pending === "" && values.length > 0) {
              onChange(values.slice(0, -1));
            }
          }}
          placeholder={placeholder}
          className={cn(inputCls, "flex-1")}
        />
        <button
          type="button"
          onClick={commit}
          disabled={!pending.trim()}
          className="flex items-center justify-center h-9 w-9 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

function UsedByPill({ icon: Icon, label }: { icon: React.ElementType; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground">
      <Icon className="h-3 w-3" />
      {label}
    </span>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────

function emptyToNull(v: string | null | undefined): string | null {
  const t = (v ?? "").trim();
  return t === "" ? null : t;
}

function arrEq(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}
