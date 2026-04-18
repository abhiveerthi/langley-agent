import Link from "next/link";
import {
  ArrowRight,
  Compass,
  Megaphone,
  MessageCircle,
  Handshake,
  Scissors,
  Sparkles,
  Zap,
} from "lucide-react";
import { WaitlistForm } from "@/components/landing/WaitlistForm";

const agents = [
  {
    icon: Compass,
    title: "Strategist",
    tagline: "Decides what to make next.",
    points: [
      "Pulls channel analytics + niche trends weekly",
      "Ranks video ideas grounded in data, not vibes",
      "Drafts scripts, hooks, and cold opens on request",
    ],
  },
  {
    icon: Megaphone,
    title: "Publisher",
    tagline: "Ships every video, everywhere.",
    points: [
      "Writes titles, descriptions, tags, chapters",
      "Repurposes each upload into tweets, threads, and posts",
      "One video in, a week of content out",
    ],
  },
  {
    icon: MessageCircle,
    title: "Community Manager",
    tagline: "Talks to your audience so you don't have to.",
    points: [
      "Triages comments — surfaces real questions, hides spam",
      "Drafts replies in your voice for you to approve",
      "Pings you when a superfan or big creator drops in",
    ],
  },
  {
    icon: Handshake,
    title: "Brand Manager",
    tagline: "Gets you paid.",
    points: [
      "Drafts cold outreach and sponsor follow-ups",
      "Tracks deal stages — pitched, negotiating, signed",
      "Writes a tailored pitch for any brand on request",
    ],
  },
];

const steps = [
  {
    n: "01",
    title: "Connect your channel",
    body: "Sign in and link your YouTube. Your team reads the last 90 days of your analytics, comments, and uploads.",
  },
  {
    n: "02",
    title: "Chat with your team",
    body: "Ask your Strategist what's next. Ask your Publisher to package yesterday's upload. Everything runs in one thread.",
  },
  {
    n: "03",
    title: "Review, approve, post",
    body: "Humans stay in the loop on anything touching the outside world — emails sent, posts published, deals signed.",
  },
];

export default function LandingPage() {
  return (
    <div className="relative flex min-h-screen flex-col overflow-x-hidden">
      {/* Nav */}
      <header className="sticky top-0 z-40 w-full border-b border-border/60 bg-background/70 backdrop-blur-md">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-sm">
              <Zap className="h-3.5 w-3.5" strokeWidth={2.5} />
            </div>
            <span className="text-[15px] font-semibold tracking-tight">Backroom</span>
          </Link>
          <nav className="flex items-center gap-1 sm:gap-2">
            <a
              href="#team"
              className="hidden rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground sm:inline-block"
            >
              Team
            </a>
            <a
              href="#how"
              className="hidden rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground sm:inline-block"
            >
              How it works
            </a>
            <Link
              href="/login"
              className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              Sign in
            </Link>
            <a
              href="#waitlist"
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary-hover"
            >
              Early access
            </a>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="relative isolate">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-grid opacity-40" />
        <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[500px] hero-glow sm:h-[700px]" />

        <div className="mx-auto w-full max-w-6xl px-4 pb-16 pt-12 sm:px-6 sm:pb-24 sm:pt-20 lg:px-8 lg:pt-28">
          <div className="mx-auto max-w-3xl text-center">
            <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-border/80 bg-card/50 px-3 py-1 text-xs text-muted-foreground backdrop-blur">
              <span className="flex h-1.5 w-1.5 rounded-full bg-primary" />
              In use by a 700k-subscriber channel — opening seats now
            </div>

            <h1 className="mt-6 text-balance text-4xl font-semibold tracking-tight text-foreground sm:text-5xl md:text-6xl lg:text-[68px] lg:leading-[1.05]">
              The AI production team every{" "}
              <span className="text-primary">YouTuber</span> wishes they could
              afford.
            </h1>

            <p className="mx-auto mt-5 max-w-2xl text-pretty text-base text-muted-foreground sm:mt-6 sm:text-lg">
              Backroom is a chat-first workspace where four AI specialists run
              your back office — strategy, publishing, community, and sponsors
              — so you can focus on making videos.
            </p>

            <div id="waitlist" className="mx-auto mt-8 w-full max-w-xl sm:mt-10">
              <WaitlistForm size="large" />
            </div>

            <div className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                Free AI strategy report on signup
              </span>
              <span className="hidden h-1 w-1 rounded-full bg-muted-foreground/30 sm:inline-block" />
              <span>No credit card</span>
              <span className="hidden h-1 w-1 rounded-full bg-muted-foreground/30 sm:inline-block" />
              <span>Cancel anytime</span>
            </div>
          </div>
        </div>
      </section>

      {/* Social proof / stat strip */}
      <section className="border-y border-border/60 bg-card/30">
        <div className="mx-auto grid w-full max-w-6xl grid-cols-2 gap-px bg-border/60 sm:grid-cols-4">
          {[
            { k: "4", v: "Specialist agents" },
            { k: "1", v: "Shared context" },
            { k: "$0", v: "To join the waitlist" },
            { k: "700k+", v: "Subs already using it" },
          ].map((s) => (
            <div key={s.v} className="bg-background px-4 py-6 text-center sm:py-8">
              <p className="text-2xl font-semibold text-foreground sm:text-3xl">
                {s.k}
              </p>
              <p className="mt-1 text-xs text-muted-foreground sm:text-sm">{s.v}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Team / Agents */}
      <section id="team" className="relative py-20 sm:py-28">
        <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
              Meet the team
            </p>
            <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl md:text-[44px]">
              Four specialists. One chat.
            </h2>
            <p className="mt-4 text-pretty text-base text-muted-foreground sm:text-lg">
              Each agent owns a job that would otherwise need a full-time hire.
              They share context — so what your Strategist learns, your
              Publisher uses.
            </p>
          </div>

          <div className="mt-12 grid grid-cols-1 gap-4 sm:mt-16 sm:grid-cols-2 sm:gap-5 lg:gap-6">
            {agents.map(({ icon: Icon, title, tagline, points }) => (
              <div
                key={title}
                className="group relative overflow-hidden rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/40 sm:p-7"
              >
                <div className="flex items-start gap-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20 sm:h-11 sm:w-11">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-lg font-semibold text-foreground sm:text-xl">
                      {title}
                    </h3>
                    <p className="mt-0.5 text-sm italic text-muted-foreground">
                      {tagline}
                    </p>
                  </div>
                </div>
                <ul className="mt-5 space-y-2.5 text-sm text-muted-foreground">
                  {points.map((p) => (
                    <li key={p} className="flex items-start gap-2.5">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                      <span className="leading-relaxed">{p}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          {/* Coming soon: Editor */}
          <div className="mt-6 rounded-xl border border-dashed border-border bg-card/40 p-5 sm:mt-8 sm:p-7">
            <div className="flex items-start gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground sm:h-11 sm:w-11">
                <Scissors className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-lg font-semibold text-foreground sm:text-xl">
                    Editor
                  </h3>
                  <span className="rounded-full border border-border bg-background px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    Coming soon
                  </span>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Cuts your long-form videos into ready-to-post shorts.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Why / moat */}
      <section className="relative border-t border-border/60 bg-card/30 py-20 sm:py-28">
        <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-2 lg:gap-16">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                The unlock
              </p>
              <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl md:text-[44px]">
                The agents share context.
              </h2>
              <p className="mt-4 text-pretty text-base text-muted-foreground sm:text-lg">
                A 500k-subscriber channel needs a 4-person team to stay
                competitive — $15–30k/month in payroll. Backroom compresses
                that team into one chat at a fraction of the cost.
              </p>
              <p className="mt-4 text-pretty text-base text-muted-foreground sm:text-lg">
                Your Strategist&apos;s weekly brief informs your Publisher&apos;s
                titles, which your Community Manager uses to answer comments,
                which your Brand Manager cites when pitching sponsors. No
                other tool does this — because no other tool is a team.
              </p>
            </div>

            <div className="relative">
              <div className="rounded-xl border border-border bg-background p-4 shadow-2xl shadow-primary/5 sm:p-5">
                <div className="flex items-center gap-2 border-b border-border pb-3">
                  <span className="h-2.5 w-2.5 rounded-full bg-muted" />
                  <span className="h-2.5 w-2.5 rounded-full bg-muted" />
                  <span className="h-2.5 w-2.5 rounded-full bg-muted" />
                  <span className="ml-2 text-xs text-muted-foreground">
                    Backroom — #general
                  </span>
                </div>
                <div className="space-y-4 pt-4 text-sm">
                  <div>
                    <p className="text-xs text-muted-foreground">You</p>
                    <p className="mt-0.5 text-foreground">
                      Strategist, what should I film this weekend?
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-primary">
                      Strategist
                    </p>
                    <p className="mt-0.5 leading-relaxed text-foreground">
                      Your last 5 uploads that beat baseline all opened with a
                      personal stakes hook. A deep-dive on the OpenAI ruling
                      fits your audience — it&apos;s trending +340% this week.
                      Draft outline in your doc.
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">You</p>
                    <p className="mt-0.5 text-foreground">
                      Publisher, package yesterday&apos;s upload.
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-primary">Publisher</p>
                    <p className="mt-0.5 leading-relaxed text-foreground">
                      Done. Title/description/chapters pushed. Generated 3
                      tweets, a LinkedIn post, and an IG caption — awaiting
                      your review.
                    </p>
                  </div>
                </div>
              </div>
              <div className="pointer-events-none absolute -inset-x-4 -bottom-4 -top-4 -z-10 rounded-2xl bg-primary/10 blur-2xl" />
            </div>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="relative py-20 sm:py-28">
        <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
              How it works
            </p>
            <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl md:text-[44px]">
              Three steps to a full back office.
            </h2>
          </div>

          <div className="mt-12 grid grid-cols-1 gap-4 sm:mt-16 sm:grid-cols-3 sm:gap-6">
            {steps.map((s) => (
              <div
                key={s.n}
                className="rounded-xl border border-border bg-card p-5 sm:p-7"
              >
                <p className="font-mono text-sm text-primary">{s.n}</p>
                <h3 className="mt-3 text-lg font-semibold text-foreground sm:text-xl">
                  {s.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {s.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="relative border-t border-border/60 py-20 sm:py-28">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-full bg-grid opacity-20" />
        <div className="pointer-events-none absolute inset-x-0 top-0 h-full hero-glow opacity-50" />
        <div className="relative mx-auto w-full max-w-3xl px-4 text-center sm:px-6 lg:px-8">
          <h2 className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl md:text-5xl">
            Stop hiring. Start shipping.
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-pretty text-base text-muted-foreground sm:text-lg">
            Seats are limited during early access. Drop your email and your
            channel — we&apos;ll send back a free AI strategy report while you
            wait.
          </p>
          <div className="mx-auto mt-8 max-w-xl">
            <WaitlistForm size="large" />
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border/60 py-8">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-3 px-4 sm:flex-row sm:px-6 lg:px-8">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-primary/15 text-primary">
              <Zap className="h-3 w-3" strokeWidth={2.5} />
            </div>
            <span className="text-sm font-medium text-foreground">Backroom</span>
            <span className="text-xs text-muted-foreground">
              © {new Date().getFullYear()}
            </span>
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <Link href="/login" className="transition-colors hover:text-foreground">
              Sign in
            </Link>
            <a href="#waitlist" className="inline-flex items-center gap-1 transition-colors hover:text-foreground">
              Early access
              <ArrowRight className="h-3 w-3" />
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
