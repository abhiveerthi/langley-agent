# Backroom

**The AI production team every YouTuber wishes they could afford.**

Backroom is a chat-first workspace where four AI specialists run the back office of your channel — strategy, publishing, community, and sponsors — so you can focus on making videos.

---

## Meet your team

### Strategist
*Decides what to make next.*
- Pulls your channel analytics and niche trends every week
- Ships a ranked brief of video ideas grounded in data, not vibes
- Drafts scripts, hooks, and cold opens on request

### Publisher
*Ships every video, everywhere.*
- Writes titles, descriptions, tags, chapters, and pinned comments in your voice
- Repurposes each upload into tweets, LinkedIn posts, IG captions, and newsletter drafts
- One video in, a week of content out

### Community Manager
*Talks to your audience so you don't have to.*
- Triages comments — surfaces real questions, flags collab DMs, hides spam
- Drafts replies in your voice for you to approve
- Pings you when a superfan or a bigger creator drops in

### Brand Manager
*Gets you paid.*
- Drafts cold outreach to sponsors and follow-ups
- Tracks deal stages — pitched, replied, negotiating, signed
- Writes the pitch for a specific brand on request

### Editor *(coming soon)*
Cuts your long-form videos into ready-to-post shorts.

---

## Why Backroom

A 500k-subscriber channel needs a 4-person team to stay competitive — $15–30k/month in payroll. Backroom compresses that team into one chat at a fraction of the cost.

The real unlock: **the agents share context.** Your Strategist's weekly brief informs your Publisher's titles, which your Community Manager uses to answer comments, which your Brand Manager cites when pitching sponsors. No other tool does this — because no other tool is a team.

---

## How it works

1. Sign in and connect your YouTube channel.
2. Chat with your team. *"Strategist, what's my next video?"* — *"Publisher, package yesterday's upload."*
3. Review, approve, post. Humans stay in the loop on anything that touches the outside world — emails sent, posts published, deals signed.

---

## Landing page

A single-page landing with waitlist capture lives at [apps/web](apps/web/). Visitors drop an email + channel URL and get a **free AI content strategy report** for their channel when we launch — generated live by the Strategist on sign-up.

---

## Tech

- **Frontend:** Next.js 16, TypeScript, Tailwind, shadcn/ui
- **Backend:** FastAPI, LangGraph agents, SSE streaming
- **Data:** Supabase (Postgres + Auth + Realtime), RLS-scoped per channel
- **Monorepo:** Turborepo + pnpm

See [packages/agents/AGENTS.md](packages/agents/AGENTS.md) for the agent roster and capabilities.

---

## MVP build order

1. **Landing page + waitlist** with channel URL capture
2. **Strategist** — weekly brief generator (doubles as the lead-magnet report)
3. **Publisher** — upload packaging + cross-platform repurposing
4. **Community Manager** — comment triage + reply drafts
5. **Brand Manager** — sponsor pitch drafting + deal tracking
6. **Editor** — post-MVP

---

## Status

In use by a 700k-subscriber YouTube channel. Productizing now for wider release.
