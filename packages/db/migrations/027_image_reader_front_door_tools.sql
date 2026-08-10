-- Image Reader becomes the full Slack DM front door (Aug 2026).
--
-- The 2026-08-06 client direction confirmed Slack as Braden's primary (and
-- effectively only) interactive surface, so the DM front-door agent grows
-- the two old-system capabilities he actively uses there:
--   send_email    — ad-hoc email to any address with CC, via Resend
--   remember_fact — explicit "remember this" into agent_memory
--
-- Mirrors packages/agents/image_reader/manifest.json for rows seeded by
-- 018 before this manifest change (new orgs pick it up from
-- registry.default_agent_seeds()). The agents.tools/capabilities columns
-- are display metadata the frontend reads; actual tool binding is code.
update agents
   set tools = '["delegate_task","send_email","remember_fact"]'::jsonb,
       capabilities = '["vision","ocr","analysis","trend-analysis","research-reports","transcription","delegation","email-sending","long-term-memory"]'::jsonb
 where slug = 'image-reader' and is_system;
