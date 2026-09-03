# Backroom Launch Tracker — Positively American (Braden Langley)

Live runbook for getting the platform in Braden's hands. Worked top to bottom;
status is updated as each item closes. Owners: **You** (Abhi), **Braden**,
**Mike** (relays to Braden), **Me** (automation/Claude).

Environment: API `https://langley-api-staging.onrender.com` · Web
`https://langley-web-staging.onrender.com` · Supabase `langley-staging` ·
Slack app "Backroom Staging" (A0BSKDBKF53). Secrets live in `.env.staging`.

## Already done

- [x] API + web deployed on Render (auto-deploy from `main`, migrations self-applying)
- [x] Supabase project, all 30 migrations, auth configured
- [x] Slack app created; scopes fixed (`im:history`, `files:read`, `reactions:write`)
- [x] CORS, OAuth-callback redirect, migration-path, and login-UX bugs fixed
- [x] Braden's org "Positively American" built: Braden = owner, Kaydi = member,
      agents seeded (Content Agent dark), brand profile (`conservative-firearms`),
      podcast brand set, **Dropbox transplanted** (verified live), Higgsfield keys set
- [x] Old bot: all three fix rounds live (Aug-6 bugs, history-mined bugs, voice memos)
- [x] Smoke test passed on the "Abhi Test" workspace (Brand Manager replied correctly)

## 1 · Before the onboarding call — our side

| # | Item | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 1 | **OpenAI API key** | You → Me | 🔵 NEXT | Powers Whisper-grade voice **and** the memory feature (embeddings). Create at platform.openai.com, paste it; I set `OPENAI_API_KEY` + `TRANSCRIPTION_PROVIDER=openai`. ~$5 lasts months. |
| 2 | **Google OAuth test user** | You → Me | ⏳ WAITING | Google shows an "unverified app" wall to anyone not listed as a test user. Tell me which Google Cloud project owns the OAuth client; I add `braden@langleyfirearmsacademy.com` (or you add him under OAuth consent screen → Test users). |
| 3 | **Rotate Braden's temp password** | Me | 🕒 AT CALL TIME | Set to a random value nobody holds, right before the magic link is minted. |
| 4 | **Rename Slack app** "Backroom Staging" → "Backroom" | You → Me | ⚪ OPTIONAL | Cosmetic. Needs a fresh app-config token (api.slack.com/apps → Your App Configuration Tokens); the previous one expired. |

## 2 · During the call — Braden's side (~15 min, Mike on the line)

| # | Item | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 5 | **Magic link** | Me → Mike → Braden | 🕒 AT CALL TIME | I mint it live (expires in ~1h); Mike relays on WhatsApp; Braden clicks and lands in his furnished workspace. |
| 6 | **Connect Slack** | Braden | 🕒 AT CALL TIME | Integrations → Connect Slack → install into The Second Press. Agent channels appear and introduce themselves; voice works there immediately (paid workspace). |
| 7 | **Connect YouTube** | Braden | 🕒 AT CALL TIME | The important one — unlocks upload detection + analytics. Depends on item 2. |
| 8 | **Connect Monday** | Braden | 🕒 AT CALL TIME | Needed for the review board when the Content Agent wakes. Harmless now. |
| 9 | **Connect X** | Braden | ⚪ DEFERRABLE | Posting needs a paid X API tier; skip if the call runs long. |

## 3 · Waiting on Braden — independent of the call

| # | Item | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 10 | **Higgsfield API credits** | Braden (Mike nudging) | 🔴 BLOCKED | Still `not_enough_credits` as of the Aug 29 test. Buy at cloud.higgsfield.ai (~2 credits/clip). I re-test on request; the same command produces a real clip once credits land. |

## 4 · After the call — switching things on

| # | Item | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 11 | **Flip the scheduler** (`SCHEDULER_ENABLED=true`) | Me | ⏳ AFTER 6–7 | Turns on upload detection + the daily b-roll batch. Then Braden gives the B-Roll channel a weekly direction; daily production starts, capped at 20 clips/day by default. |
| 12 | **Kaydi's login** | Me → Mike → Kaydi | ⏳ WHEN WANTED | Same magic-link move. |

## 5 · Phase 2 — deliberately parked

| # | Item | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 13 | Content Agent switch-on · podcast lane · Instagram (Meta review) · Opus Clip key · Riverside · Google app verification (before public auto-uploads) | Braden / Mike / Me | ⚪ LATER | Per the Aug 6 call: infrastructure built, not plugged in until Braden says go. |

## Hygiene (any time)

- [ ] Revoke the Supabase account token used for setup (supabase.com/dashboard/account/tokens) — You
- [ ] Rotate the Higgsfield secret after go-live is confirmed (it traveled over WhatsApp) — Braden
