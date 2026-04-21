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

> The legacy scaffolds (`comms/`, `core/`, `general/`, `intel/`, `research/`) remain in the tree. `core/` is shared infrastructure (`BaseAgent`, tracker, prompts) and stays. The others are earlier experiments that the new roster supersedes.

---

## Strategist

**Decides what to make next.**

The analytics-and-ideation brain. Doubles as the waitlist lead magnet — on signup, it generates a free AI strategy report for the creator's channel.

**Capabilities**
- Pulls channel analytics + niche trends weekly
- Ranks video ideas grounded in data, not vibes
- Drafts scripts, hooks, and cold opens on request
- Watches competitor channels for gaps

**Inputs** Channel ID, last 90 days of analytics, recent uploads, niche keywords
**Outputs** Ranked brief of video ideas with rationale, optional script/outline/hook
**Integrations** YouTube (required), Google Docs (optional, for brief delivery)
**Typical tools** `youtube_get_analytics`, `youtube_search`, `youtube_get_video`, `web_search`, `gdocs_create`
**Approval gates** None — read-only agent, nothing hits the outside world

---

## Publisher

**Ships every video, everywhere.**

Takes one video in and produces a week of content out.

**Capabilities**
- Writes titles, descriptions, tags, chapters, and pinned comments in the creator's voice
- Repurposes each upload into tweets, LinkedIn posts, IG captions, newsletter drafts
- Schedules cross-platform posts

**Inputs** Fresh upload + transcript, voice/style reference doc, target platforms
**Outputs** Packaged YouTube metadata, platform-specific post drafts, scheduling plan
**Integrations** YouTube (required), Google Docs + Slack (optional)
**Typical tools** `youtube_get_video`, `youtube_update_video`, `gdocs_create`, `slack_post_message`
**Approval gates** `update_video_metadata`, `publish_social_post`

> Full product & UX spec: [publisher/PRODUCT.md](publisher/PRODUCT.md) — input model, workflow, launch vs v2 scope, required tool additions.

---

## Community Manager

**Talks to your audience so you don't have to.**

**Capabilities**
- Triages comments — surfaces real questions, flags collab DMs, hides spam
- Drafts replies in the creator's voice for approval
- Pings the creator when a superfan or larger creator drops in

**Inputs** Comment stream, VIP list, auto-hide rules, voice reference
**Outputs** Prioritized comment queue, draft replies, VIP alerts
**Integrations** YouTube (required), Slack (optional, for VIP pings)
**Typical tools** `youtube_get_comments`, `youtube_reply_comment`, `youtube_moderate_comment`, `slack_post_message`
**Approval gates** `reply_comment`, `moderate_comment`, `send_dm` (replies can be whitelisted per channel)

---

## Brand Manager

**Gets you paid.**

**Capabilities**
- Drafts cold outreach to sponsors and follow-ups
- Tracks deal stages — pitched, replied, negotiating, signed
- Writes a tailored pitch for any brand on request

**Inputs** Media kit / rate card, brand name, channel fit signals, prior thread history
**Outputs** Tailored pitch email, follow-up schedule, updated deal pipeline
**Integrations** Gmail + Google Docs (required), Slack / YouTube (optional)
**Typical tools** `gmail_send`, `gmail_search`, `gmail_get_thread`, `gdocs_create`, `web_search`
**Approval gates** `send_email`, `log_deal_status_change`

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
