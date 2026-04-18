-- Early access waitlist for the Backroom landing page.
-- Writes come from the server-side API route using the service role key,
-- so RLS is enabled and no public policies are defined (service role bypasses RLS).

create table if not exists early_access_signups (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  channel_url text,
  source text default 'landing',
  ip_address text,
  user_agent text,
  referrer text,
  invited_at timestamptz,
  created_at timestamptz not null default now()
);

create unique index if not exists early_access_signups_email_key
  on early_access_signups (lower(email));

create index if not exists early_access_signups_created_at_idx
  on early_access_signups (created_at desc);

alter table early_access_signups enable row level security;

-- No policies on purpose: only the service role (used by the API route) can read/write.
