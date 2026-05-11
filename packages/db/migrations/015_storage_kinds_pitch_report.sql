-- Extend storage_assets.kind to include the two missing agent-export kinds:
--
--   'pitch'  — Brand Manager exports a snapshot of every pitch it sends
--              (subject + body + recipient as Markdown). The send-via-Resend
--              path already logs to brand_deals; this is the human-readable
--              record the creator can reopen later.
--   'report' — Community Manager exports the full structured triage payload
--              after each run so the creator can scroll back through which
--              comments were classified as VIP / question / spam, plus the
--              draft replies the agent proposed.
--
-- The original check constraint shipped with migration 008. Postgres does not
-- have an "alter check constraint" so we drop and re-add. The migration runner
-- (scripts/migrate.ts) applies in filename order; existing rows are unaffected
-- because all current values still satisfy the new list.
alter table storage_assets drop constraint if exists storage_assets_kind_check;

alter table storage_assets add constraint storage_assets_kind_check check (
  kind in (
    'upload', 'brief', 'package', 'script',
    'thumbnail', 'image', 'video', 'audio',
    'pitch', 'report',
    'other'
  )
);
