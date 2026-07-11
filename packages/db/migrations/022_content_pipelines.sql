-- Content Agent (Agent #5, "Force Multiplier") pipeline tracking.
--
-- One row per (org, video): the durable record of a detected upload moving
-- through the repurposing pipeline — audio extraction → clip generation →
-- podcast draft → review queue → two-tier approval → publish fan-out.
--
-- The LangGraph run (checkpointed on `thread_id`) is the *executor*; this
-- table is the *ledger*. The graph can pause for days at the approval gate,
-- but dashboards, the scheduler, and retry logic all read pipeline progress
-- from here without touching LangGraph checkpoints. `stages` records
-- per-stage outcomes (status, timestamps, errors) so a failure is
-- attributable to one stage; `assets` accumulates the generated artifacts
-- (clips, audio file, podcast episode) that later become Monday.com review
-- items and, on approval, publish targets.
--
-- unique(org_id, video_id) makes dispatch idempotent: a scheduler retry of
-- the same upload upserts into the same pipeline instead of forking a second
-- run for the same video.

create table if not exists content_pipelines (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,
  video_id text not null,
  video_title text,
  -- 'short' | 'longform' | 'live' — classified from video metadata (duration /
  -- liveStreamingDetails). Drives asset choices: a live stream becomes the
  -- podcast episode; a longform becomes clips; a short may pass through.
  video_kind text,
  -- Pipeline lifecycle. Text (not enum) so adding stages doesn't need a
  -- migration: detected → processing → ready_for_review → approved →
  -- publishing → published | failed.
  status text not null default 'detected',
  -- LangGraph thread driving this pipeline (checkpointer key). Lets an
  -- operator resume/inspect the paused graph from the pipeline row.
  thread_id text,
  -- Per-stage ledger: {"extract_audio": {"status": "done", "at": ...}, ...}
  stages jsonb not null default '{}',
  -- Generated artifacts: [{"kind": "clip"|"audio"|"podcast_episode", ...}]
  assets jsonb not null default '[]',
  error text,
  detected_at timestamptz not null default now(),
  published_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, video_id)
);

-- Dashboard hot path: "this org's recent pipelines, newest first".
create index if not exists idx_content_pipelines_org_detected
  on content_pipelines (org_id, detected_at desc);

-- ── Row Level Security ──────────────────────────────────────────────────────
-- Same posture as youtube_poll_state (017): members can READ their org's
-- pipelines for the dashboard; all writes come from the service-role runner
-- (scheduler dispatch + graph nodes), never a browser session.
alter table content_pipelines enable row level security;

create policy "members can read own org content_pipelines"
  on content_pipelines for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));
