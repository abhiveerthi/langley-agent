-- Channel read state — per-(user, channel) "last seen" timestamps so the
-- sidebar can render unread badges and the FE can mark channels read on
-- view.
--
-- Why a timestamp and not a `last_read_message_id`:
--   - Lookups are simpler — `count(*) where created_at > last_read_at` is
--     a single index hit on `(channel_id, created_at desc)` (already
--     present from migration 012).
--   - Realtime arrivals can't temporarily "rewind" what counts as new —
--     the timestamp is monotonic, message-id ordering can interleave on
--     concurrent inserts.
--   - Migrating the value forward as the user scrolls a busy channel is
--     a single UPDATE; no need to "find the row by id" first.
--
-- Composite primary key on (user_id, channel_id) gives us upsert-on-view
-- for free without a separate unique index.

create table if not exists channel_reads (
  user_id uuid not null references users(id) on delete cascade,
  channel_id uuid not null references channels(id) on delete cascade,
  last_read_at timestamptz not null default now(),
  primary key (user_id, channel_id)
);

-- For the sidebar query: "for this user, give me last_read_at for every
-- channel they've opened". Already covered by the PK, but explicit index
-- makes the intent clear and helps if we ever change the PK shape.
create index if not exists idx_channel_reads_user
  on channel_reads (user_id);

alter table channel_reads enable row level security;

-- A user can read + upsert their own rows. No-one reads anyone else's
-- read receipts — that's a "who's online" feature for a future PR.
create policy "users read own channel_reads"
  on channel_reads for select
  using (user_id = auth.uid());

create policy "users upsert own channel_reads"
  on channel_reads for insert
  with check (user_id = auth.uid());

create policy "users update own channel_reads"
  on channel_reads for update
  using (user_id = auth.uid());
