-- Unified asset library for the org. One row per file in the `org-assets`
-- Storage bucket. The bucket holds the bytes; this table holds the metadata
-- the UI surfaces (kind, tags, source, size, mime, soft-delete).
--
-- Path layout in the bucket: `<org_id>/<kind>/<filename>` so a single RLS
-- policy on storage.objects keys off the first path segment to scope access
-- to org members. The DB-side RLS on storage_assets mirrors that.
--
-- Sources of an asset:
--   - 'user'         — drag-drop upload from the Storage page
--   - '<agent_slug>' — exported by an agent (Brief→MD, Package→JSON, etc).
--                      Future PR; the source/source_id columns are seeded now
--                      so the export feature doesn't need a follow-up migration.

create table if not exists storage_assets (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,
  -- Path inside the org-assets bucket. Always prefixed with `<org_id>/`
  -- so storage RLS can scope by foldername.
  storage_path text not null,
  -- Display name. Decoupled from path so renaming doesn't move bytes.
  filename text not null,
  size_bytes bigint,
  mime_type text,
  -- Drives the left-rail tab on the Storage page. Every asset has exactly
  -- one kind; cross-cutting categorization lives in `tags`.
  kind text not null check (kind in (
    'upload', 'brief', 'package', 'script', 'thumbnail', 'image', 'video', 'audio', 'other'
  )),
  tags text[] not null default '{}',
  source text,           -- 'user' or an agent slug
  source_id uuid,        -- e.g. strategist_briefs.id when source='strategist'
  uploaded_by uuid references users(id),
  notes text,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, storage_path)
);

create index if not exists idx_storage_assets_org_kind_recent
  on storage_assets (org_id, kind, created_at desc);
create index if not exists idx_storage_assets_tags
  on storage_assets using gin (tags);
create index if not exists idx_storage_assets_org_archived
  on storage_assets (org_id, archived_at);

alter table storage_assets enable row level security;

drop policy if exists "members read own org storage_assets" on storage_assets;
create policy "members read own org storage_assets"
  on storage_assets for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

drop policy if exists "members insert own org storage_assets" on storage_assets;
create policy "members insert own org storage_assets"
  on storage_assets for insert
  with check (org_id in (select org_id from org_members where user_id = auth.uid()));

drop policy if exists "members update own org storage_assets" on storage_assets;
create policy "members update own org storage_assets"
  on storage_assets for update
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

drop policy if exists "members delete own org storage_assets" on storage_assets;
create policy "members delete own org storage_assets"
  on storage_assets for delete
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- ── Supabase Storage bucket + policies ────────────────────────────────────
-- Private bucket. Uploads/downloads go through Supabase Storage's auth using
-- the user's JWT; service-role can sign URLs for server-side flows.

insert into storage.buckets (id, name, public)
values ('org-assets', 'org-assets', false)
on conflict (id) do nothing;

drop policy if exists "members read own org storage objects" on storage.objects;
create policy "members read own org storage objects"
  on storage.objects for select to authenticated
  using (
    bucket_id = 'org-assets'
    and (storage.foldername(name))[1] in (
      select org_id::text from org_members where user_id = auth.uid()
    )
  );

drop policy if exists "members upload own org storage objects" on storage.objects;
create policy "members upload own org storage objects"
  on storage.objects for insert to authenticated
  with check (
    bucket_id = 'org-assets'
    and (storage.foldername(name))[1] in (
      select org_id::text from org_members where user_id = auth.uid()
    )
  );

drop policy if exists "members update own org storage objects" on storage.objects;
create policy "members update own org storage objects"
  on storage.objects for update to authenticated
  using (
    bucket_id = 'org-assets'
    and (storage.foldername(name))[1] in (
      select org_id::text from org_members where user_id = auth.uid()
    )
  );

drop policy if exists "members delete own org storage objects" on storage.objects;
create policy "members delete own org storage objects"
  on storage.objects for delete to authenticated
  using (
    bucket_id = 'org-assets'
    and (storage.foldername(name))[1] in (
      select org_id::text from org_members where user_id = auth.uid()
    )
  );
