-- Org invites: lets an org owner pull a teammate into their workspace.
--
-- We don't issue our own magic tokens here — Supabase Auth's
-- `admin.inviteUserByEmail()` does that and handles the email send,
-- expiry, and single-use semantics. This table just records *which org*
-- the invited email maps to (Supabase doesn't know about Backroom orgs)
-- and the delivery channel(s) the owner picked.
--
-- Acceptance flow: invitee clicks the Supabase magic link → lands on
-- /auth/callback in the web app → callback exchanges the code for a
-- session and calls POST /api/invites/:id/complete, which inserts an
-- org_members row with role='limited' and sets accepted_at here.
--
-- The 'limited' role is the v1 hedge against the most predictable
-- "wait, the editor can read all my sponsor pricing?" reaction: it
-- gates SELECT on brand_deals and org_profiles. Everything else stays
-- flat-access. Roles + write-side gating land in v2.

create table if not exists org_invites (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs(id) on delete cascade,

  -- Always lowercase + trimmed at the API layer; the CHECK enforces it
  -- so a stray Mixed-Case email can't sneak past the partial unique
  -- index below and create a duplicate outstanding invite.
  email text not null check (email = lower(trim(email))),

  invited_by uuid not null references users(id),

  -- 'email' uses Supabase Auth invite email; 'slack' posts the magic
  -- link to a chosen channel via the org's existing Slack bot; 'both'
  -- does both. Slack bot can't DM users, so the channel is owner-picked.
  delivery_method text not null check (delivery_method in ('email', 'slack', 'both')),
  slack_channel_id text,

  -- Stamped by the API on send. last_delivery_error surfaces in the
  -- team settings UI so the owner sees "Sent 14:22" or "Failed:
  -- rate limited 14:22 - retry" instead of a silent pending row.
  last_delivery_attempt_at timestamptz,
  last_delivery_error text,

  accepted_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);

-- Partial unique: at most one OUTSTANDING invite per (org, email).
-- Revoked or accepted rows don't block re-invite, which is the bug
-- a full unique constraint would create when an expired invite needs
-- to be reissued.
create unique index if not exists org_invites_active_uniq
  on org_invites (org_id, email)
  where revoked_at is null and accepted_at is null;

create index if not exists idx_org_invites_email on org_invites (email);

alter table org_invites enable row level security;

create policy "members can read own org invites"
  on org_invites for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can insert own org invites"
  on org_invites for insert
  with check (org_id in (select org_id from org_members where user_id = auth.uid()));

create policy "members can update own org invites"
  on org_invites for update
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- Limited-read hedge: invitees default to role='limited', and the two
-- most sensitive tables (sponsor deals + brand profile data) require a
-- non-limited role for SELECT. Writes on those tables stay org-scoped
-- without role gating in v1 because the UI doesn't expose write surfaces
-- to limited members; defense-in-depth on writes lands in v2.
--
-- Anyone with role 'owner' (auto-provisioned creators) or 'member'
-- (legacy schema default, treated as full-access for backwards compat)
-- continues to see brand_deals and org_profiles unchanged.

drop policy if exists "members can read own org brand_deals" on brand_deals;
create policy "non-limited members can read own org brand_deals"
  on brand_deals for select
  using (
    org_id in (
      select org_id from org_members
      where user_id = auth.uid() and role != 'limited'
    )
  );

drop policy if exists "members can read own org profile" on org_profiles;
create policy "non-limited members can read own org profile"
  on org_profiles for select
  using (
    org_id in (
      select org_id from org_members
      where user_id = auth.uid() and role != 'limited'
    )
  );
