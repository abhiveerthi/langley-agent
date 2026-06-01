-- Seed the Image Reader / Voice agent into every existing org.
--
-- Same rationale as 014_seed_default_agents.sql: the `agents` table is the
-- canonical per-org store the @mention autocomplete, mention parser, and
-- channel dispatch all read. 014 backfilled the original five-agent roster;
-- this is the matching one-time backfill for the sixth agent (image-reader)
-- so `@image-reader` resolves in every existing workspace, not just orgs
-- created after it shipped.
--
-- New orgs are seeded by the signup hook in apps/api/app/dependencies.py
-- (_provision_personal_workspace), which reads packages/agents/registry.py's
-- default_agent_seeds() — once the registry includes ImageReaderAgent, new
-- orgs get it automatically; this migration covers the ones that already exist.
--
-- The metadata fields (description, icon, capabilities, tools) mirror
-- packages/agents/image_reader/manifest.json. `is_system = true` marks it as
-- built-in; `active = true` so it shows up in @mention autocomplete (it's a
-- live agent, not a coming-soon stub). `tools` is an empty array because
-- vision/OCR run on the model directly and transcription is a graph node —
-- the agent exposes no LLM-callable tools.
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
        'image-reader',
        'Image Reader',
        'Reads screenshots with native vision — YouTube analytics, competitor channels, news articles, social posts, bills/lawsuits, infographics — extracts the figures, summarizes, analyzes (including trends across multiple shots), and files a Markdown report to the Storage Library. Also transcribes voice notes into text so you can talk instead of type.',
        'scan-eye',
        '["vision","ocr","analysis","transcription"]'::jsonb,
        '[]'::jsonb,
        true,
        true
      )
    on conflict (org_id, slug) do nothing;
  end loop;
end $$;
