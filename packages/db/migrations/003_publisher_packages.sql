-- Publisher-generated metadata + social kits, one row per (org, video).
-- Created by the Publisher agent's persist_package node; pushed to YouTube
-- via the approval-gated update_video_metadata flow.

create table if not exists publisher_packages (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,
  video_id text not null,
  video_title text not null,
  status text not null default 'generating'
    check (status in ('generating', 'draft', 'pending_push', 'pushed')),
  title_variants jsonb default '[]',
  description text,
  tags text[] default '{}',
  chapters jsonb default '[]',
  pinned_comment text,
  thumbnail_ideas jsonb default '[]',
  -- { "twitter": "...", "newsletter": "..." } — more platforms later
  social jsonb default '{}',
  warning text,
  approval_id uuid references approvals(id) on delete set null,
  youtube_pushed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, video_id)
);

create index if not exists idx_publisher_packages_org
  on publisher_packages (org_id, updated_at desc);

alter table publisher_packages enable row level security;

-- Mirrors the read policy used by threads / approvals — direct reads only for
-- org members. Server writes go through the service role and bypass RLS.
create policy "members can read own org publisher_packages"
  on publisher_packages for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can update own org publisher_packages"
  on publisher_packages for update
  using (org_id in (select org_id from org_members where user_id = auth.uid()));
