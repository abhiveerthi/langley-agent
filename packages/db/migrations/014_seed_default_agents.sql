-- Seed the five default agents into every org.
--
-- Rationale: the `agents` table is referenced by three live code paths —
--   1. `@mention` autocomplete                 (apps/api/app/routers/channels.py)
--   2. mention parsing in channel messages     (apps/api/app/routers/channels.py)
--   3. channel dispatch's sender_agent_id      (apps/api/app/services/channel_dispatch.py)
-- — but until now nothing inserted rows. Result: a freshly-signed-up org
-- could see agent cards on /app/agents (hardcoded in the FE) but `@strategist`
-- in a team channel would silently drop, and dispatch would post
-- "isn't registered for this workspace".
--
-- This migration backfills every existing org with the 5-agent roster
-- defined in packages/agents/registry.py. New orgs are seeded by the
-- signup hook in apps/api/app/dependencies.py (_provision_personal_workspace),
-- so this migration is the one-time backfill.
--
-- The metadata fields (description, icon, capabilities, tools) mirror each
-- agent's manifest.json in packages/agents/<agent>/. If those manifests
-- change, the agents table is the canonical per-org store — re-syncing is
-- a future concern (probably a startup job in apps/api), not this migration.
--
-- `is_system = true` marks these as built-in vs custom agents an org
-- might one day install. `active` defaults to true except for the editor,
-- which is a coming-soon stub (status flagged in its manifest).
do $$
declare
  org_row record;
begin
  for org_row in select id from orgs loop
    insert into agents (org_id, slug, name, description, icon, capabilities, tools, is_system, active)
    values
      (
        org_row.id,
        'strategist',
        'Strategist',
        'Decides what to make next. Pulls channel analytics and niche trends weekly, ships ranked video-idea briefs grounded in data, and drafts scripts, hooks, and cold opens on request.',
        'compass',
        '["analytics","research","ideation","writing","scripting"]'::jsonb,
        '["youtube_get_analytics","youtube_search","youtube_get_video","web_search","gdocs_create","gdocs_update"]'::jsonb,
        true,
        true
      ),
      (
        org_row.id,
        'publisher',
        'Publisher',
        'Ships every video, everywhere. Writes titles, descriptions, tags, chapters, and pinned comments in the creator''s voice, then repurposes each upload into tweets, LinkedIn posts, IG captions, and newsletter drafts.',
        'megaphone',
        '["writing","seo","publishing","repurposing"]'::jsonb,
        '["youtube_get_video","youtube_update_video","gdocs_create","gdocs_update","slack_post_message"]'::jsonb,
        true,
        true
      ),
      (
        org_row.id,
        'community-manager',
        'Community Manager',
        'Talks to your audience so you don''t have to. Triages comments, surfaces real questions, flags collab DMs, hides spam, drafts replies in the creator''s voice, and pings the creator when a superfan or larger creator shows up.',
        'message-circle',
        '["moderation","triage","writing","communication"]'::jsonb,
        '["youtube_get_comments","youtube_reply_comment","youtube_moderate_comment","slack_post_message","gmail_send"]'::jsonb,
        true,
        true
      ),
      (
        org_row.id,
        'brand-manager',
        'Brand Manager',
        'Gets you paid. Drafts cold outreach to sponsors, researches target brands, sends approved pitches via Resend, and tracks deal stages.',
        'handshake',
        '["outreach","sales","crm","writing"]'::jsonb,
        '["find_sponsor_leads","research_brand","get_channel_stats","send_pitch_email"]'::jsonb,
        true,
        true
      ),
      (
        org_row.id,
        'editor',
        'Editor',
        'Cuts long-form videos into ready-to-post shorts. Selects highlight moments, applies the brand template, overlays captions, and exports in platform-specific formats.',
        'scissors',
        '["video-processing","transcription","captioning","editing"]'::jsonb,
        '["youtube_get_video","transcribe_video","extract_highlight_clip","render_short"]'::jsonb,
        true,
        false  -- coming-soon: hidden from @mention autocomplete (which filters active=true)
      )
    on conflict (org_id, slug) do nothing;
  end loop;
end $$;
