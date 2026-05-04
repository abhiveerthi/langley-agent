-- Store the Supabase Auth magic link on the invite row so the team page
-- can offer a "Copy link" affordance. The owner shares the link manually
-- when needed:
--   - while a sending domain is being verified at Resend (delivery to
--     non-self recipients fails, but the link is still valid)
--   - to anyone who prefers Slack DM, iMessage, or any out-of-band channel
--   - as a backup if the recipient never received the email
--
-- The link itself is the same URL Resend's email and the Slack-channel
-- post embed; we just persist it so it can be re-displayed without
-- regenerating against Supabase Auth (which would invalidate the old
-- token). Cross-tenant exposure is RLS-gated by the existing org_invites
-- policies — only org members see their org's links.

alter table org_invites add column if not exists magic_link text;
