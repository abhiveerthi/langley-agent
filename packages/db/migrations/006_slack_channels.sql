-- Maps Slack workspace channels (and individual Slack threads within them)
-- onto Marcus orgs + agents + threads.
--
-- Two row shapes share this table by design:
--   - "Channel mapping" row: slack_thread_root_ts IS NULL. Inserted at OAuth
--     time; says "this Slack channel routes to this agent for this org".
--   - "Per-thread mapping" row: slack_thread_root_ts is the ts of the user's
--     top-level Slack message that started a thread. Inserted lazily by the
--     Slack runner the first time a top-level message arrives. Maps a Slack
--     thread to a stable Marcus thread_id so reply messages in the Slack
--     thread continue the same Marcus conversation (checkpointer state too).
--
-- Postgres treats NULL as distinct in unique constraints, so the channel
-- mapping row coexists with any number of per-thread rows on the same
-- slack_channel_id. Lookups for the channel mapping use IS NULL explicitly.

create table if not exists slack_channels (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,
  agent_slug text not null,
  slack_team_id text not null,
  slack_channel_id text not null,
  slack_thread_root_ts text,
  marcus_thread_id uuid not null,
  created_at timestamptz not null default now(),
  unique (slack_channel_id, slack_thread_root_ts)
);

create index if not exists idx_slack_channels_team
  on slack_channels (slack_team_id, slack_channel_id);
create index if not exists idx_slack_channels_org_agent
  on slack_channels (org_id, agent_slug);

alter table slack_channels enable row level security;

create policy "members can read own org slack_channels"
  on slack_channels for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Phase C prep: when an approval card is rendered in Slack, store the
-- Slack message ts so the future button-handler can chat.update the same
-- card to "Approved/Rejected" after resolution.
alter table approvals
  add column if not exists slack_message_ts text,
  add column if not exists slack_channel_id text;
