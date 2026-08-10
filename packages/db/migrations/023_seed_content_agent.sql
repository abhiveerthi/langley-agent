-- Seed the Content Agent (Agent #5, "Force Multiplier") into every existing org.
--
-- Same rationale as 014/018/020: the `agents` table is the canonical per-org
-- store that @mention autocomplete, the mention parser, and channel dispatch
-- read. New orgs get the agent from registry.default_agent_seeds() via the
-- signup hook; this is the one-time backfill for orgs that already exist.
--
-- Metadata mirrors packages/agents/content/manifest.json. `active = false`:
-- the agent ships DARK per the 2026-08-06 client call ("build it, don't
-- plug it in") — the upload poller checks this flag before dispatching, so
-- nothing automated runs until the org's row is flipped to active. That
-- flip (plus config like podcast_enabled) is the go-live switch.
--
-- on conflict (org_id, slug) do nothing keeps this idempotent.
do $$
declare
  org_row record;
begin
  for org_row in select id from orgs loop
    insert into agents (org_id, slug, name, description, icon, capabilities, tools, is_system, active)
    values
      (
        org_row.id,
        'content',
        'Content Agent',
        'Turns every new YouTube upload into a full content drop: extracts podcast audio, generates short clips, drafts the podcast episode with chapters, queues everything for two-step review, and publishes approved assets across platforms. Watches the channel automatically — no manual kickoff needed.',
        'workflow',
        '["repurposing","clip-generation","podcast-production","auto-publishing"]'::jsonb,
        '["get_pipeline_status"]'::jsonb,
        true,
        false
      )
    on conflict (org_id, slug) do nothing;
  end loop;
end $$;
