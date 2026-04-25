-- Local-only seed data. Runs on `supabase db reset` for dev environments;
-- NEVER applied to production migrations.
--
-- This is where we put fixture orgs that local devs use to exercise agents
-- without touching real client data. Production seeds should NEVER end up
-- in this file — they belong in real migrations or partner's signup flow.

-- ── Test fixture: gaming channel ──────────────────────────────────────────
-- Replaces the old config/orgs/test-gaming-channel.yaml. Used as the
-- generic "test against an unrelated channel" sandbox. The youtube_channel_id
-- below points at a real public channel (MrBeast Gaming) — convenient for
-- read-only verification, but DO NOT enable any write actions
-- (reply_to_comment, update_video_metadata) against this fixture; we don't
-- own that channel.

-- Stable UUID so local tests can reference it deterministically.
do $$
declare
  fixture_org_id uuid := '00000000-0000-0000-0000-000000000001';
begin
  insert into orgs (id, name, slug, plan, settings, created_at)
  values (
    fixture_org_id,
    'PixelDrift (test fixture)',
    '_fixture-pixeldrift',
    'fixture',
    '{}'::jsonb,
    now()
  )
  on conflict (id) do nothing;

  insert into org_profiles (
    org_id,
    brand_name,
    brand_voice,
    brand_primary_email,
    niche_slug,
    audience_size,
    youtube_channel_id,
    owners,
    is_fixture
  )
  values (
    fixture_org_id,
    'PixelDrift',
    'hype, casual, knowledgeable, slightly irreverent',
    'list@pixeldrift.gg',
    'gaming',
    '~250k subscribers',
    'UCIPPMRA040LQr5QPyJEbmXA',  -- MrBeast Gaming, read-only verification
    '["test@pixeldrift.gg"]'::jsonb,
    true
  )
  on conflict (org_id) do nothing;
end $$;
