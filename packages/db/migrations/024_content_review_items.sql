-- Content Agent Phase C: Monday.com review-queue item tracking.
--
-- The two-tier approval ("Kaydi first-line, Braden final — no Slack, no
-- extra logins, everything lives in Monday") is driven by Monday board
-- items: one item per generated asset (the reviewer's first-line pass) plus
-- one FINAL item per video (the owner's publish gate). When someone flips
-- an item's Approval status column, Monday fires our webhook; this table is
-- how the webhook maps a bare monday_item_id back to the pipeline + asset
-- it governs, and where each decision is recorded.
--
-- Deliberately separate from content_pipelines.assets (jsonb): the webhook
-- lookup path ("which pipeline does item 12345 belong to?") needs an
-- indexed equality query, not jsonb containment scans.

create table if not exists content_review_items (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,
  pipeline_id uuid references content_pipelines(id) on delete cascade,
  video_id text not null,
  board_id text not null,
  monday_item_id text not null,
  -- 'asset' items are the reviewer's first-line pass; the single 'final'
  -- item per video is the owner's publish gate.
  role text not null default 'asset',
  -- Index into content_pipelines.assets for role='asset'; null for 'final'.
  asset_index int,
  kind text,
  decision text not null default 'pending',  -- pending | approved | rejected
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, monday_item_id)
);

-- Webhook hot path: item lookup is covered by the unique index above.
-- Pipeline roll-up ("are all of this video's items decided?"):
create index if not exists idx_content_review_items_org_video
  on content_review_items (org_id, video_id);

alter table content_review_items enable row level security;

create policy "members can read own org content_review_items"
  on content_review_items for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- ── Review board provisioning (service-role ONLY) ───────────────────────────
-- One row per org: the provisioned Monday board, its Approval column, and
-- the webhook secret embedded in the subscription URL. Deliberately NOT in
-- agents.config: that jsonb is member-readable (RLS select + GET /api/agents
-- returns it wholesale), and the webhook secret is the ONLY authentication
-- on the public webhook endpoint — a member who read it could forge
-- approval decisions. RLS is enabled with NO member policies, so only the
-- service-role client (the provisioner and the webhook router) can touch it.
create table if not exists content_review_boards (
  org_id uuid primary key references orgs(id) on delete cascade,
  board_id text not null,
  status_column_id text,
  webhook_id text,
  webhook_secret text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table content_review_boards enable row level security;
-- (no policies on purpose — see header)
