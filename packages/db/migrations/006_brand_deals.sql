-- Brand Manager's deal pipeline. One row per sponsor we've pitched, tracked
-- through the lifecycle (pitched → replied → negotiating → signed | declined | paused).
--
-- Auto-populated by Brand Manager's `_send_email_node` when an approved pitch
-- actually goes out via Resend. Read by:
--   - Brand Manager itself via the `list_active_deals` tool — surfaces the
--     pipeline when the user asks "who have we pitched"
--   - Other agents via `packages/agents/core/peer_context.py:active_deals`
--     — Strategist briefs and CM replies can reference deal context
--
-- Stage updates beyond initial pitch (replied, negotiating, signed) are
-- expected to come from a future settings/inbox UI or from inbound webhook
-- handling (Brand Manager email-reply handling — backlog item #6). For
-- this branch the table only auto-writes on the initial pitched row.

create table if not exists brand_deals (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,
  -- Loose link to the chat thread the pitch was drafted in. Optional —
  -- thread might be cleaned up before the deal moves through stages.
  thread_id uuid,
  -- Free-text brand name. The Brand Manager pulls this from the user's
  -- request verbatim ("pitch Magpul" → brand_name="Magpul"). A future
  -- settings UI can let the user clean these up.
  brand_name text not null,
  recipient text,         -- email address that received the pitch
  subject text,           -- subject line of the sent pitch
  stage text not null default 'pitched'
    check (stage in ('pitched', 'replied', 'negotiating', 'signed', 'declined', 'paused')),
  -- Resend message id when available — supports later "did this bounce" /
  -- "show me the original" features without needing a separate event log.
  external_message_id text,
  notes text,             -- free-text annotations, set by stage updates
  pitched_at timestamptz default now(),
  last_updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index if not exists idx_brand_deals_org_recent
  on brand_deals (org_id, last_updated_at desc);
create index if not exists idx_brand_deals_org_stage
  on brand_deals (org_id, stage);

alter table brand_deals enable row level security;

-- Members of the org read their pipeline. Writes happen via the service role
-- (Brand Manager's send_email node + future stage-update flows).
create policy "members can read own org brand_deals"
  on brand_deals for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));
