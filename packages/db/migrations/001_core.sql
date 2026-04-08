-- Enable required extensions
create extension if not exists "pgvector";

-- Organizations (one per client / workspace)
create table orgs (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text unique not null,
  plan text default 'starter',
  settings jsonb default '{}',
  created_at timestamptz default now()
);

-- Users (members of orgs)
create table users (
  id uuid primary key references auth.users(id) on delete cascade,
  email text unique not null,
  full_name text,
  avatar_url text,
  created_at timestamptz default now()
);

-- Org memberships
create table org_members (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  user_id uuid references users(id) on delete cascade,
  role text default 'member',
  created_at timestamptz default now(),
  unique(org_id, user_id)
);

-- Projects
create table projects (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  name text not null,
  description text,
  status text default 'active',
  color text default '#6366F1',
  icon text,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- Agents registered in the system
create table agents (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  name text not null,
  slug text not null,
  description text,
  icon text,
  capabilities jsonb default '[]',
  tools jsonb default '[]',
  config jsonb default '{}',
  is_system boolean default false,
  active boolean default true,
  created_at timestamptz default now(),
  unique(org_id, slug)
);

-- Chat threads
create table threads (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  user_id uuid references users(id),
  agent_id uuid references agents(id),
  project_id uuid references projects(id),
  title text,
  status text default 'active',
  metadata jsonb default '{}',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Messages in threads
create table messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid references threads(id) on delete cascade,
  role text not null,
  content text,
  tool_calls jsonb,
  tool_results jsonb,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- Tasks
create table tasks (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  project_id uuid references projects(id),
  thread_id uuid references threads(id),
  agent_id uuid references agents(id),
  created_by uuid references users(id),
  title text not null,
  description text,
  status text default 'pending',
  priority text default 'medium',
  type text default 'manual',
  input jsonb default '{}',
  output jsonb,
  scheduled_at timestamptz,
  cron_expression text,
  due_at timestamptz,
  completed_at timestamptz,
  requires_approval boolean default false,
  approved_by uuid references users(id),
  approved_at timestamptz,
  metadata jsonb default '{}',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Agent run records (one per graph invocation)
create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  thread_id uuid references threads(id),
  task_id uuid references tasks(id),
  agent_id uuid references agents(id),
  status text default 'running',
  input jsonb,
  output jsonb,
  error text,
  steps jsonb default '[]',
  tool_calls jsonb default '[]',
  input_tokens int default 0,
  output_tokens int default 0,
  cost_usd numeric(10,6) default 0,
  started_at timestamptz default now(),
  completed_at timestamptz,
  metadata jsonb default '{}'
);

-- Human-in-the-loop approval requests
create table approvals (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  run_id uuid references agent_runs(id),
  task_id uuid references tasks(id),
  thread_id uuid references threads(id),
  requested_by_agent text,
  action_type text not null,
  action_payload jsonb not null,
  preview text,
  status text default 'pending',
  reviewed_by uuid references users(id),
  reviewed_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz default now()
);

-- Notifications
create table notifications (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  user_id uuid references users(id),
  type text not null,
  title text not null,
  body text,
  action_url text,
  read boolean default false,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- Integration connections (OAuth tokens per org)
create table integrations (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  provider text not null,
  status text default 'active',
  access_token text,
  refresh_token text,
  token_expires_at timestamptz,
  scopes jsonb default '[]',
  metadata jsonb default '{}',
  created_at timestamptz default now(),
  unique(org_id, provider)
);

-- Usage log for billing / cost tracking
create table usage_log (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  agent_id uuid references agents(id),
  run_id uuid references agent_runs(id),
  model text not null,
  input_tokens int default 0,
  output_tokens int default 0,
  cost_usd numeric(10,6) default 0,
  created_at timestamptz default now()
);

-- Agent memory (vector embeddings for RAG)
create table agent_memory (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  agent_id uuid references agents(id),
  thread_id uuid references threads(id),
  content text not null,
  embedding vector(1536),
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- ── Indexes ──
create index idx_threads_org on threads(org_id, created_at desc);
create index idx_messages_thread on messages(thread_id, created_at);
create index idx_agent_runs_org on agent_runs(org_id, status, created_at desc);
create index idx_tasks_org on tasks(org_id, status, created_at desc);
create index idx_approvals_org on approvals(org_id, status, created_at desc);
create index idx_notifications_user on notifications(user_id, read, created_at desc);
create index idx_usage_log_org on usage_log(org_id, created_at);
create index idx_agent_memory_embedding on agent_memory using ivfflat (embedding vector_cosine_ops);

-- ── Row Level Security ──
alter table orgs enable row level security;
alter table org_members enable row level security;
alter table threads enable row level security;
alter table messages enable row level security;
alter table tasks enable row level security;
alter table approvals enable row level security;
alter table notifications enable row level security;
alter table agents enable row level security;
alter table projects enable row level security;
alter table integrations enable row level security;

-- ── RLS Policies ──

-- Orgs: members can read their own orgs
create policy "members can read own orgs" on orgs for select
  using (id in (select org_id from org_members where user_id = auth.uid()));

-- Org members: members can see their org's members
create policy "members can read own org members" on org_members for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Threads: members can CRUD their own org threads
create policy "members can read own org threads" on threads for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can insert own org threads" on threads for insert
  with check (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can update own org threads" on threads for update
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Messages: members can read messages in their org threads
create policy "members can read own org messages" on messages for select
  using (thread_id in (
    select id from threads where org_id in (
      select org_id from org_members where user_id = auth.uid()
    )
  ));

create policy "members can insert own org messages" on messages for insert
  with check (thread_id in (
    select id from threads where org_id in (
      select org_id from org_members where user_id = auth.uid()
    )
  ));

-- Tasks: members can CRUD their org's tasks
create policy "members can read own org tasks" on tasks for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can insert own org tasks" on tasks for insert
  with check (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can update own org tasks" on tasks for update
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Approvals
create policy "members can read own org approvals" on approvals for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can update own org approvals" on approvals for update
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Notifications: users can read their own notifications
create policy "users can read own notifications" on notifications for select
  using (user_id = auth.uid());

create policy "users can update own notifications" on notifications for update
  using (user_id = auth.uid());

-- Agents: members can read their org's agents
create policy "members can read own org agents" on agents for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Projects: members can CRUD their org's projects
create policy "members can read own org projects" on projects for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can insert own org projects" on projects for insert
  with check (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can update own org projects" on projects for update
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Integrations: members can read their org's integrations
create policy "members can read own org integrations" on integrations for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));
