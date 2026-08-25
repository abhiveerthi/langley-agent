# Go-Live Checklist — Langley Agent

Order matters: **deploy the backend first** (nothing the client touches works
without a public, always-on API), then wire providers, then flip the client's
accounts. Every integration key is plug-and-play — the feature activates the
moment its key is in the environment; no redeploy needed for key changes.

---

## 1. Deploy the backend (Render)

- [ ] Create the service from `render.yaml` (Dashboard → New → Blueprint), or a
      Docker web service pointed at `apps/api/Dockerfile` with build context `.`.
- [ ] **`numInstances: 1`** — do not scale. The scheduler runs in-process; two
      instances = duplicate agent runs and duplicate paid renders. (See the note
      in `render.yaml`.)
- [ ] Plan = **Starter or higher** (the free tier sleeps when idle, which kills
      the scheduler — the nightly pipeline would never fire).
- [ ] Pre-Deploy Command = `python /app/scripts/migrate.py` (applies migrations
      022–025 and everything prior; idempotent — see `ops/render-deploy.md`).
- [ ] Health check path = `/api/health`.
- [ ] Deploy the web frontend (`apps/web`) — Render second service or Vercel.
      Note its URL; it's the OAuth-redirect + CORS origin below.

## 2. Core environment (set in the dashboard — `sync: false` values)

- [ ] `SCHEDULER_ENABLED=true` — **the master switch.** Without it, the upload
      poller and the daily b-roll sweep never run. Everything automated is dark
      until this is `true`.
- [ ] `DATABASE_URL` — prod Postgres, **session mode (port 5432)**, not the 6543
      transaction pooler (breaks prepared statements).
- [ ] `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- [ ] `ANTHROPIC_API_KEY`, `JWT_SECRET`, `ENCRYPTION_KEY`
- [ ] `API_URL` = this service's public URL · `APP_URL` = the web URL (this is
      the var the API's CORS allowlist reads — `NEXT_PUBLIC_*` vars belong to
      the web service, not the API).

## 3. OAuth apps (our side — one-time)

For each provider, register the app and set the redirect URI to the **web app
URL** (`https://<web>/auth/<provider>/callback`):

- [ ] **Google** (YouTube + Gmail): `GOOGLE_CLIENT_ID/SECRET`. ⚠️ For public
      video uploads, submit the app for **Google's OAuth verification/audit** —
      unverified apps get uploads forced to private. Start this early; it's slow.
- [ ] **Slack**: `SLACK_CLIENT_ID/SECRET/SIGNING_SECRET`. In the Slack app
      config, enable Event Subscriptions → request URL `https://<api>/api/slack/events`,
      subscribe to **`message.groups`** and **`message.im`** (DMs), and add the
      **`im:history`** scope. Without `message.im` + `im:history`, DMs to the bot
      go nowhere. Also add **`reactions:write`** — the bot 👀-reacts to every
      message as an instant "heard you" ack (degrades silently without it).
- [ ] **Monday**: `MONDAY_CLIENT_ID/SECRET`. The review-board webhook
      self-registers on first pipeline run — it just needs `API_URL` publicly
      reachable (it retries every run until it sticks).
- [ ] **Dropbox**: `DROPBOX_CLIENT_ID/SECRET` (b-roll + podcast package delivery).
- [ ] **X/Twitter**: `TWITTER_CLIENT_ID/SECRET`. Posting needs a **paid X API
      tier** (Basic+) — confirm the dev account level.
- [ ] **Resend**: `RESEND_API_KEY`, `EMAIL_FROM` (verified domain, SPF+DKIM).

## 4. Agent integration keys (from the client, arriving this week)

Each is independent; set it and its feature turns on:

- [ ] `TRANSCRIPTION_PROVIDER=openai` + `OPENAI_API_KEY` — **strongly recommended**
      for Braden's accuracy requirement (~$0.33/day for the episode; local
      Whisper fallback works but is noticeably worse on mobile audio).
- [ ] `HIGGSFIELD_API_KEY` + `HIGGSFIELD_API_SECRET` — issued as a PAIR
      (cloud.higgsfield.ai/api-keys); both required. **Live-verified 8/25:
      the pair authenticates**, and the platform API has NO text2video —
      clips render as a two-step chain, text2image (Soul) → image2video
      (DoP), models set by `HIGGSFIELD_T2I_MODEL` / `HIGGSFIELD_I2V_MODEL`
      (defaults verified against the account's GET /models roster; DoP lite
      = 2 credits/clip, so the default 20-clip day ≈ 40 credits).
      ⚠️ **BLOCKER: the API credit pool is currently EMPTY** (submits return
      403 not_enough_credits — it's a separate pool from Braden's web
      subscription). Braden must add API credits at cloud.higgsfield.ai,
      then run ONE clip through chat as the end-to-end check.
- [ ] `OPUSCLIP_API_KEY` — auto-clipping (check the client's plan tier includes
      API access; until then Opus stays manual and the stage records "skipped").
- [ ] `RIVERSIDE_API_KEY` — **optional.** Audio is auto-extracted from the
      YouTube upload without it; only needed for studio-grade podcast audio.
- [ ] `INSTAGRAM_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID` — dormant until
      the client's Meta Business account + app review clears (longest lead time).

**Not needed** (per the 7/11 client thread): Spotify, Apple Podcasts, Podbean/
Podigee APIs. The podcast episode is packaged to Dropbox; Braden uploads to
Podbean manually (`podcast_publish_mode` defaults to `manual`).

## 5. Per-org enablement (in-app, once the org exists)

- [ ] **Content Agent (Agent #5) ships DARK — leave it off at launch.** Per the
      8/6 client call ("build it, don't plug it in"): the agent seeds with
      `agents.active = false`, so the upload poller never dispatches it. When
      Braden gives the word, flipping the org's `agents.active` row to true is
      the entire go-live — no deploy. At that point also set:
      - `escalation_slack_channel_id` = Braden's Slack channel (failure alerts
        go to him, not Kaydi).
      - `podcast_brand` = "Positively American with Braden Langley".
      - `podcast_enabled = true` **only when the podcast strategy is settled**
        (paused pending his PR consultant) — until then even the nightly live
        stream routes to clips only.
- [ ] B-Roll config → `daily_production_enabled = true` **and** a
      `weekly_direction` — the sweep skips any org missing either (no direction =
      no spend, by design). `daily_clip_target` defaults to **20**; Braden
      scales it on request ("create 10 / 20 / 100 clips") up to the 150 cap.
- [ ] Connect the org's integrations in-app: YouTube, Slack, Monday, Dropbox, X.

## 6. Smoke test (before telling the client it's live)

- [ ] `GET https://<api>/api/health` → `{"status":"ok"}`.
- [ ] Post in a Slack agent channel → get a reply. DM the bot → get a reply.
- [ ] Drop a screenshot in Slack → Image Reader analyzes it.
- [ ] Send a voice memo → transcribed and answered.
- [ ] Manually trigger a Content run on a test video (works even while the
      agent is dark — only the automatic upload dispatch is gated) → items
      appear on the Monday board **with playable media links**; flip the FINAL
      item → publish fan-out runs (targets that have keys publish; others
      record "skipped").
- [ ] Confirm a b-roll batch lands in Dropbox (needs Higgsfield + Dropbox).
- [ ] Hand Mike `docs/client-guide-langley.md` for Braden & Kaydi.
