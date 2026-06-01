-- Seed the B-Roll Producer agent into every existing org.
--
-- Same rationale as 014_seed_default_agents.sql / 018_seed_image_reader_agent.sql:
-- the `agents` table is the canonical per-org store the @mention autocomplete,
-- mention parser, and channel dispatch all read. 014 backfilled the original
-- five-agent roster and 018 added the sixth (image-reader); this is the matching
-- one-time backfill for the seventh agent (broll) so `@broll` resolves in every
-- existing workspace, not just orgs created after it shipped.
--
-- New orgs are seeded by the signup hook in apps/api/app/dependencies.py
-- (_provision_personal_workspace), which reads packages/agents/registry.py's
-- default_agent_seeds() — once the registry includes BRollAgent, new orgs get
-- it automatically; this migration covers the ones that already exist.
--
-- The metadata fields (description, icon, capabilities, tools) mirror
-- packages/agents/broll/manifest.json. `is_system = true` marks it as built-in;
-- `active = true` so it shows up in @mention autocomplete (it's a live agent,
-- not a coming-soon stub). `tools` carries the one LLM-callable tool
-- (generate_broll_clip).
--
-- on conflict (org_id, slug) do nothing keeps this idempotent and harmless to
-- re-run.
do $$
declare
  org_row record;
begin
  for org_row in select id from orgs loop
    insert into agents (org_id, slug, name, description, icon, capabilities, tools, is_system, active)
    values
      (
        org_row.id,
        'broll',
        'B-Roll Producer',
        'Writes original b-roll scripts from your topics and weekly direction, generates short interrupt-style clips with Higgsfield (16:9 landscape + 9:16 Shorts, ~5–10s), and files them in your connected Dropbox organized by date and topic. Scripting works today; clip rendering activates once a Higgsfield key is added.',
        'clapperboard',
        '["scripting","video-generation","organization"]'::jsonb,
        '["generate_broll_clip"]'::jsonb,
        true,
        true
      )
    on conflict (org_id, slug) do nothing;
  end loop;
end $$;
