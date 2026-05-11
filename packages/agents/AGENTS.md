# Marcus — Agent Roster

The Marcus team is five specialists that share context across a single chat workspace. Each agent owns a job that would otherwise need a full-time hire. What the Strategist learns, the Publisher uses; what the Publisher ships, the Community Manager fields questions on; what the Community Manager hears, the Brand Manager cites when pitching sponsors.

Live agent manifests are co-located with each agent:

| Slug | Name | Tagline | Manifest | Status |
|---|---|---|---|---|
| `strategist` | Strategist | Decides what to make next. | [strategist/manifest.json](strategist/manifest.json) | active |
| `publisher` | Publisher | Ships every video, everywhere. | [publisher/manifest.json](publisher/manifest.json) | active |
| `community-manager` | Community Manager | Talks to your audience so you don't have to. | [community_manager/manifest.json](community_manager/manifest.json) | active |
| `brand-manager` | Brand Manager | Gets you paid. | [brand_manager/manifest.json](brand_manager/manifest.json) | active |
| `editor` | Editor | Cuts long-form videos into ready-to-post shorts. | [editor/manifest.json](editor/manifest.json) | coming soon |

> Shared infrastructure lives in `core/` (`BaseAgent`, profile loader, peer-context helper, prompt rendering) and is used by every agent.

---

## Strategist

**Decides what to make next.**

The analytics-and-ideation brain. Doubles as the waitlist lead magnet — on signup, it generates a free AI strategy report for the creator's channel.

**Capabilities**
- Pulls channel analytics + niche trends weekly
- Ranks video ideas grounded in data, not vibes
- Drafts scripts, hooks, and cold opens on request
- Watches competitor channels for gaps

**Inputs** Channel ID (resolved from OAuth), last 90 days of analytics, recent uploads, niche keywords
**Outputs** Ranked brief — persisted to `strategist_briefs`, exported as Markdown to Storage Library, and one workspace task per ranked idea
**Integrations** YouTube (required, OAuth for analytics)
**Typical tools** `get_channel_stats`, `get_recent_video_performance`, `search_niche_trends`, `search_competitor_videos`, `get_channel_analytics_overview`
**Approval gates** None — read-only agent, nothing hits the outside world

> **v2 plan:** Google Docs export, dedicated script/outline tool, ad-hoc one-video deep dives.

---

## Publisher

**Ships every video, everywhere.**

Takes one video in and produces a week of content out.

**Capabilities**
- Writes titles, descriptions, tags, chapters, and pinned comments in the creator's voice
- Drafts a tweet + an email newsletter (subject + body) per upload
- Pushes metadata to YouTube, posts the tweet to X, and sends the newsletter via the connected Gmail account — all gated

**Inputs** Fresh upload + transcript, voice/style reference doc
**Outputs** Packaged YouTube metadata, tweet copy, newsletter (subject + body)
**Integrations** YouTube (required), X / Twitter (optional, for tweet push), Gmail (optional, for newsletter send)
**Typical tools** `get_video_details`, `get_video_transcript`, `update_video_metadata`, `post_tweet`, `send_newsletter_via_gmail`
**Approval gates** `update_video_metadata`, `post_tweet`, `send_newsletter_via_gmail` — three lanes, one shared `approval_gate` node, intent-aware routing

> Full product & UX spec: [publisher/PRODUCT.md](publisher/PRODUCT.md) — input model, workflow, launch vs v2 scope, required tool additions.

---

## Community Manager

**Talks to your audience so you don't have to.**

**Capabilities**
- Triages comments — surfaces real questions, flags collab DMs, hides spam
- Drafts replies in the creator's voice for approval
- Pings the creator when a superfan or larger creator drops in

**Inputs** Comment stream, VIP list, voice reference
**Outputs** Prioritized comment queue, draft replies, archived triage report
**Integrations** YouTube (required, OAuth — for both reads and the reply write)
**Typical tools** `get_recent_comments`, `lookup_channel`
**Approval gates** `reply_to_comment` — single lane through the shared `approval_gate` node; the reply tool is invoked from the send node only after the gate clears (not exposed as a callable tool to the LLM).

> **v2 plan:** Comment moderation (`hide_comment`, `pin_comment`), Slack VIP ping, rejection→revise loop on rejected drafts.

---

## Brand Manager

**Gets you paid.**

**Capabilities**
- Drafts tailored cold pitches to sponsors using channel stats + brand research
- Sends approved pitches via Resend (server-side API key — no per-user OAuth)
- Logs each sent pitch to `brand_deals` as `pitched` for the pipeline view

**Inputs** Brand name (or "find leads in my niche"), channel stats, prior thread context
**Outputs** Tailored pitch email (subject + body), updated deal pipeline row
**Integrations** Resend (required, for sending), YouTube (optional, for stats lookup)
**Typical tools** `find_sponsor_leads`, `research_brand`, `get_channel_stats`, `send_pitch_email`, `list_active_deals_tool`
**Approval gates** `send_pitch_email` — single lane through the shared `approval_gate` node

> **v2 plan:** Gmail OAuth send (so pitches come from the creator's actual address) + manual deal-status updates (`replied` / `negotiating` / `signed`).

---

## Editor *(coming soon)*

**Cuts long-form videos into ready-to-post shorts.**

**Planned capabilities**
- Extract highlight clips from uploaded raw footage
- Transcribe + overlay captions (Whisper)
- Apply brand overlay template
- Export in 9:16 / 1:1 for Shorts, TikTok, Reels

**Integrations (planned)** YouTube (required), Google Drive / Dropbox (optional, for raw footage input)
**Typical tools** `youtube_get_video`, `transcribe_video`, `extract_highlight_clip`, `render_short`
**Approval gates** `publish_short`
**Blockers** Needs a video worker service (FFmpeg / Shotstack / Creatomate) on GPU-capable infra — out of scope for MVP.

---

## Shared context model

All agents read from and write to the same per-channel store: uploads, analytics, comment history, voice reference, deal pipeline, and the running thread. This is the moat — no single-purpose tool can do this because no single-purpose tool is a team.

When adding a new agent: drop a directory here with `__init__.py`, `manifest.json`, `agent.py` (LangGraph graph), `tools.py`, and `prompts.py`. Register its class in [registry.py](registry.py).
