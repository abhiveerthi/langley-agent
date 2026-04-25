-- DB-backed per-tenant profiles. One row per org.
--
-- The OrgProfile lived in YAML (config/orgs/*.yaml) for the bespoke Langley
-- build, where new tenants meant a hand-edited config file + redeploy. With
-- partner's auto-provisioning OAuth flow, new orgs get created at runtime
-- and need a writable profile store. This is it.
--
-- The Pydantic model in packages/agents/core/profile.py is the schema authority
-- — this table mirrors it. Any new field there gets a migration here.
--
-- All columns except `org_id` are nullable: a freshly-created org has the row
-- inserted at signup time with whatever's known from the OAuth handshake
-- (e.g. brand_name from YouTube channel title), and the rest gets filled in
-- as the user completes onboarding. Agents handle partial profiles
-- gracefully — missing channel_id or niche_slug means the agent surfaces
-- "you haven't set this yet" rather than crashing.

create table if not exists org_profiles (
  org_id uuid primary key references orgs(id) on delete cascade,

  -- brand
  brand_name text,
  brand_voice text,
  brand_primary_email text,

  -- niche: slug references config/niches/<slug>.yaml (kept as YAML for now —
  -- small, stable preset list). `audience_size` is a free-text override
  -- (e.g. "~700k subscribers") that the org sets independent of the preset.
  niche_slug text,
  audience_size text,

  -- youtube
  youtube_channel_id text,

  -- meta
  owners jsonb not null default '[]',  -- list of email strings

  -- Distinguishes seeded test-fixture profiles from real client orgs so admin
  -- queries can scope cleanly. Default false so a real signup is real.
  is_fixture boolean not null default false,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_org_profiles_niche on org_profiles (niche_slug);

alter table org_profiles enable row level security;

-- Members read their own org's profile. Writes happen via the service role
-- (the API does the writes from auth-resolved contexts), so no insert/update
-- policy is defined.
create policy "members can read own org profile"
  on org_profiles for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));
