-- Scheduling / job-runner foundation for the Agent #5 "Force Multiplier"
-- new-upload poller.
--
-- Two tables:
--
--   1. `youtube_poll_state` — per-(org, channel) bookkeeping for the YouTube
--      new-upload poller. The background runner (apps/api/app/services/
--      scheduler.py) iterates orgs that have a connected YouTube integration,
--      asks the YouTube API for the channel's latest upload, and compares it
--      against `last_seen_video_id`. When it differs, it fires the Publisher
--      create_package flow for that video and advances `last_seen_video_id`
--      so a given upload only ever triggers once.
--
--   2. `scheduled_jobs` — a generic, provider-agnostic registry of recurring
--      background jobs. This is where `tasks.cron_expression` finally gets a
--      home: today those columns on `tasks` are unused. Rather than have the
--      runner scan every `tasks` row looking for a populated cron string, a
--      job is registered here once with its cron/interval and a `kind`
--      discriminator. The YouTube poller is itself representable as a
--      `kind = 'youtube_upload_poll'` row, but for v1 the poller runs on a
--      single global interval from config and only `youtube_poll_state` is
--      load-bearing. `scheduled_jobs` is laid down now so the next scheduled
--      job (e.g. weekly Strategist briefs) has a table to land in without
--      another migration, and so `tasks.cron_expression`-driven tasks can be
--      promoted into real scheduled jobs later by writing a row here that
--      points back at `tasks.id` via `payload->>'task_id'`.

-- ── YouTube new-upload poll state ──────────────────────────────────────────
-- One row per connected channel. `org_id` is the tenant; `channel_id` is the
-- creator's YouTube channel (denormalized from integrations.metadata so the
-- poller can key + index on it directly). Composite PK gives upsert-on-poll
-- for free.
create table if not exists youtube_poll_state (
  org_id uuid not null references orgs(id) on delete cascade,
  channel_id text not null,
  last_seen_video_id text,
  last_polled_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (org_id, channel_id)
);

-- The poller's hot path: "give me the poll state for this org's channel".
-- Covered by the PK, but an explicit index on org_id keeps the per-org
-- lookup intent clear.
create index if not exists idx_youtube_poll_state_org
  on youtube_poll_state (org_id);

-- ── Generic scheduled-jobs registry ────────────────────────────────────────
-- `kind` discriminates the job type (e.g. 'youtube_upload_poll'). `enabled`
-- lets an org pause a job without deleting its state. Exactly one of
-- `cron_expression` / `interval_seconds` is expected to be set; the runner
-- treats `interval_seconds` as a simpler alternative to a full cron string
-- (mirrors the unused `tasks.cron_expression` column — see header note).
create table if not exists scheduled_jobs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,
  kind text not null,
  enabled boolean not null default true,
  cron_expression text,
  interval_seconds int,
  payload jsonb not null default '{}',
  last_run_at timestamptz,
  next_run_at timestamptz,
  last_status text,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- The runner scans for enabled jobs due to run, scoped by org. A given org
-- shouldn't register the same kind twice, so enforce uniqueness on
-- (org_id, kind) — the YouTube poll job is one-per-org.
create unique index if not exists uq_scheduled_jobs_org_kind
  on scheduled_jobs (org_id, kind);

create index if not exists idx_scheduled_jobs_due
  on scheduled_jobs (enabled, next_run_at);

-- ── Row Level Security ──────────────────────────────────────────────────────
-- Consistent with migration 001's "members can read own org X" pattern. The
-- background runner uses the service-role key (bypasses RLS) for both read
-- and write; these policies exist so a member-scoped client can *read* poll
-- state / job config for an org-settings UI later. No member-facing
-- insert/update policies — scheduling state is written by the service role
-- only, never directly by a browser session.
alter table youtube_poll_state enable row level security;
alter table scheduled_jobs enable row level security;

create policy "members can read own org youtube_poll_state"
  on youtube_poll_state for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can read own org scheduled_jobs"
  on scheduled_jobs for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));
