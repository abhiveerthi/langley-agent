-- Strategist's persisted weekly briefs — one row per generated brief.
-- Written by the Strategist's persist_brief node after compose_brief.
-- Read by every agent's load_peer_context node (peer-context "moat":
-- Strategist briefs inform Publisher titles inform Community Manager
-- replies inform Brand Manager pitches).

create table if not exists strategist_briefs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,
  thread_id uuid,
  -- run_id stays nullable until the orchestrator threads it onto state;
  -- not load-bearing for peer-context reads, just for tracing.
  run_id uuid,
  headline text not null,
  ideas jsonb not null default '[]',
  created_at timestamptz not null default now()
);

-- "Latest brief for this org" is the hottest read path.
create index if not exists idx_strategist_briefs_org_created
  on strategist_briefs (org_id, created_at desc);

alter table strategist_briefs enable row level security;

-- Members of the org can read their org's briefs (mirrors the threads /
-- messages policy). Writes happen via the service role from the API, so
-- no insert/update policies are defined.
create policy "members can read own org strategist_briefs"
  on strategist_briefs for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));
