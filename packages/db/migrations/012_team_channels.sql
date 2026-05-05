-- Team channels — in-house Slack-style chat for org members + agents.
--
-- The killer feature: humans and agents are first-class participants in the
-- same channel. A user posting `@strategist what should we make next?` in
-- #content triggers the strategist agent, whose response posts back into
-- the channel as a regular message everyone can see.
--
-- v1 scope:
--   - Channels (org-scoped, all members can read/post)
--   - Plain-text messages
--   - Mentions: @username (humans) and @agent-slug (agents). Agent mentions
--     dispatch the agent's response back into the channel.
--   - Real-time delivery via Supabase Realtime (postgres-changes events)
--     subscribed by the FE.
--
-- Out of scope for v1: DMs, threads, file uploads, read state, edits.
-- Schema is shaped so each can be added without a breaking migration.

-- ── channels ─────────────────────────────────────────────────────────────
-- Channels are org-scoped. `name` is the slug-style handle ("general",
-- "marketing", "ideas") shown with a `#` prefix in the UI.
create table if not exists channels (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,
  name text not null
    check (name ~ '^[a-z0-9_-]{1,64}$'),
  description text,
  created_by uuid references users(id) on delete set null,
  created_at timestamptz not null default now(),
  archived_at timestamptz,
  -- Channel names are unique per org. Two orgs can each have a #general.
  unique (org_id, name)
);

create index if not exists idx_channels_org_active
  on channels (org_id) where archived_at is null;

-- ── channel_messages ─────────────────────────────────────────────────────
-- Polymorphic sender: exactly one of (sender_user_id, sender_agent_id) is
-- set. The CHECK constraint enforces XOR so the FE can render either a user
-- avatar or an agent badge without a join surprise.
--
-- `mentioned_user_ids` and `mentioned_agent_slugs` are denormalized at
-- write time (parsed by the API on POST) so:
--   - The FE doesn't have to re-parse the body to know who's mentioned
--   - The agent-dispatch code can find @-agent invocations cheaply via
--     the array, without re-parsing on every insert webhook
--   - Future @-mention notifications can subquery these arrays directly
--
-- `agent_run_id` and `in_reply_to_message_id` are NULL for human-authored
-- messages. For agent responses to a mention, both point back at the
-- triggering context — useful for "show me what produced this" affordances.
create table if not exists channel_messages (
  id uuid primary key default gen_random_uuid(),
  channel_id uuid not null references channels(id) on delete cascade,
  -- Denormalized org_id for fast RLS — RLS policies don't have to join
  -- through `channels` on every read. Cheap (uuid) and we never bulk-move
  -- messages between orgs, so the denorm can't drift.
  org_id uuid not null references orgs(id) on delete cascade,

  sender_user_id uuid references users(id) on delete set null,
  sender_agent_id uuid references agents(id) on delete set null,

  body text not null check (length(body) between 1 and 4000),

  mentioned_user_ids uuid[] not null default '{}',
  mentioned_agent_slugs text[] not null default '{}',

  -- Set on agent responses: the run that produced this message + the
  -- triggering user message. Both NULL on human-authored messages.
  agent_run_id uuid references agent_runs(id) on delete set null,
  in_reply_to_message_id uuid references channel_messages(id) on delete set null,

  -- v1 doesn't expose edit; column reserved so adding it later is no
  -- migration, just an UPDATE statement.
  edited_at timestamptz,

  created_at timestamptz not null default now(),

  -- Exactly one sender type populated.
  constraint channel_messages_one_sender check (
    (sender_user_id is not null)::int + (sender_agent_id is not null)::int = 1
  )
);

create index if not exists idx_channel_messages_channel_recent
  on channel_messages (channel_id, created_at desc);

-- ── channel_members ──────────────────────────────────────────────────────
-- Tracks "your channels" (the sidebar list). For v1 ALL org members can
-- read and post in ANY non-archived channel — membership is just the
-- subscription affordance, not an access gate. Future private channels
-- would gate read/post via this table.
create table if not exists channel_members (
  channel_id uuid not null references channels(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  joined_at timestamptz not null default now(),
  primary key (channel_id, user_id)
);

create index if not exists idx_channel_members_user
  on channel_members (user_id);

-- ── RLS ──────────────────────────────────────────────────────────────────
alter table channels enable row level security;
alter table channel_messages enable row level security;
alter table channel_members enable row level security;

-- Org members read all non-archived channels in their org.
create policy "members read same-org channels"
  on channels for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Org members create new channels in their org.
create policy "members create channels in own org"
  on channels for insert
  with check (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Org members read all messages in their org. Service role (the API) does
-- the @-mention parse + agent dispatch; RLS doesn't restrict the API since
-- it uses the service key.
create policy "members read same-org channel_messages"
  on channel_messages for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Org members read membership rows for any channel in their org.
create policy "members read same-org channel_members"
  on channel_members for select
  using (
    channel_id in (
      select id from channels
      where org_id in (select org_id from org_members where user_id = auth.uid())
    )
  );

-- Realtime publication — Supabase Realtime listens on this publication for
-- INSERT/UPDATE/DELETE events. Adding the table here is what lets the FE
-- subscribe via `supabase.channel(...).on('postgres_changes', ...)`.
alter publication supabase_realtime add table channel_messages;
