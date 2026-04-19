# Publisher — Product & UX Spec

Captured decisions for the Publisher agent. Read this before changing scope, tools, or the system prompt.

---

## The promise

> *"In one message, your video goes from raw export to ready-to-publish on YouTube — plus a week of social drafts you can paste."*

## Input model

**Publisher does not take raw footage.** Editing is a separate job (that's the Editor agent). Publisher's starting point is a finished video.

Two supported entry points:

1. **Creator says "package my latest"** → Publisher calls `get_latest_upload()` and pulls the newest video on the connected channel (including unlisted).
2. **Creator pastes a YouTube URL** → Publisher calls `get_video_details(video_id)` on it.

Both require YouTube **OAuth** (not just an API key) so Publisher can see the creator's unlisted videos. That's the same OAuth the landing page promises at signup.

We do NOT accept raw `.mp4` uploads in launch. Reasons:
- Requires a file-upload pipeline (Supabase Storage + chunked upload)
- Requires a transcription worker (Whisper → GPU or paid API, ~$0.006/min)
- Queue + status tracking
- Weeks of work for marginal upgrade — ~95% of creators already upload to YT as unlisted before going public

## The normal creator workflow

1. Creator exports from their editor (Premiere, CapCut, DaVinci, whatever).
2. Uploads to YouTube as **unlisted** with a placeholder title (`final_v3.mp4` is fine).
3. YouTube auto-generates captions within 5–15 minutes.
4. Creator drops into chat: *"Publisher, package my latest"*.
5. Publisher reads the transcript via captions → drafts the full kit.
6. **Approval card appears in chat:** *"Push this metadata to your video?"*
7. Creator approves → Publisher calls `videos.update` → title/desc/tags/chapters are live on the unlisted video.
8. Creator reviews in YT Studio, uploads a thumbnail, flips to public (or schedules) — those last clicks stay with the human.

The social kit is delivered in the same chat message and is **draft-only** for launch. Creator pastes into their existing scheduler (Buffer, Typefully, Hypefury).

## Intent-scoped output, not a mode switch

Two camps of creators, both served by the same agent:

- **"The title is my brand"** — writes their own metadata, wants Publisher only for cross-platform repurposing.
- **"Please just handle it"** — offloads everything.

Scope the output based on how the creator asks, not a setting:

| Ask | Output blocks |
|---|---|
| *"Package my latest"* | Title + desc + tags + chapters + pinned comment + social kit (full menu) |
| *"Repurpose this: `<url>`"* | Social kit only. Read creator's existing title/desc as voice + angle anchor. |
| *"Draft 3 title options for this"* | Titles only |
| *"Write the description"* | Description only |

**Subtle feature:** when the creator has already written a title/desc, treat it as voice signal and angle anchor — don't overwrite it, let it shape every downstream asset.

## Output format

One structured message with copy-paste-able labeled blocks:

- **Title** — 3–5 variants for A/B
- **Description** — 2-sentence hook, timestamps, links, subscribe CTA (150–250 words)
- **Tags** — 10–15, mixed head + long-tail
- **Chapters** — real timestamps from the transcript
- **Pinned comment** — a question that invites reply
- **Thumbnail text ideas** — overlay copy only (not image generation — that's Editor/designer)
- **Social kit:** 3 tweets, 1 thread outline, 1 LinkedIn post, 1 IG caption, 1 newsletter blurb

## The killer feature: one-click push to YouTube

`videos.update` (YouTube Data API, scope `youtube.force-ssl`) lets Publisher write the metadata directly to the unlisted video after approval. Chapters go into the description as formatted timestamps (YouTube parses them automatically — no separate chapters field exists).

The approval gate is already in the manifest under `interrupt_before: ["update_video_metadata", ...]`. Respect it.

## What's in launch vs. v2

| Capability | Launch | v2+ |
|---|---|---|
| Pull latest upload by channel (OAuth) | ✅ | |
| Read transcript (YT auto-captions) | ✅ | |
| Generate YT metadata kit | ✅ | |
| Push metadata to video (approval-gated) | ✅ | |
| Generate social drafts | ✅ | |
| Transcribe raw `.mp4` (Whisper worker) | ❌ | ✅ |
| Thumbnail image generation | ❌ | ✅ (likely Editor) |
| Auto-post to socials | ❌ | ✅ (Buffer integration first — one API, covers most platforms) |
| Auto-flip privacy to public | ❌ | consider — high-consequence, likely always human |
| A/B title test tracking | ❌ | ✅ (needs post-publish data loop) |

## Required tool additions before launch

Current tools ([tools.py](tools.py)): `get_video_details`, `get_video_comments`, `suggest_seo_keywords`.

Launch-blocking additions:
- `get_video_transcript(video_id)` — via YouTube `captions.download`. Without this, every output is a guess.
- `get_latest_upload()` — enables the "package my latest" entry point.
- `update_video_metadata(video_id, title, description, tags)` — the approval-gated push. Goes behind `interrupt_before`.

The first two depend on YouTube OAuth being wired in `packages/integrations/youtube/`. The third requires the `youtube.force-ssl` scope.

## Things we explicitly decided NOT to do at launch

- Raw file uploads (use the unlisted-on-YT workflow instead)
- Auto-posting to Twitter/LinkedIn/IG (per-platform API hell — Buffer is the clean v2 path)
- Thumbnail image generation (different craft; Editor/designer territory)
- Auto-flip to public (creator keeps the final click)
- Reddit/Threads/Bluesky/Mastodon drafts (diminishing returns — add on demand)
- Content calendar management (that's a dashboard, not an agent)
