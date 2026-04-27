# Render deploy + migrations

The API auto-migrates on every deploy via Render's **Pre-Deploy Command**.

## One-time setup

In the Render dashboard for the API service:

1. **Settings → Build & Deploy → Pre-Deploy Command** → set to:

   ```
   python /app/scripts/migrate.py
   ```

   This runs after the new image is built but before traffic is swapped over.
   If migrations fail, Render holds the deploy.

2. **Environment → DATABASE_URL** must already be set to the prod Postgres URL
   (port 5432 / session mode — *not* the 6543 transaction pooler, which breaks
   prepared statements). It is — same env var the API itself uses.

That's it. After this, merging to main automatically:
- triggers Render to rebuild the image;
- runs `migrate.py` against prod Postgres;
- skips already-applied files (tracked in the `_migrations` table);
- swaps in the new container only if migrations succeeded.

## Local dev

`pnpm dev` runs `pnpm db:migrate` first, then starts the dev servers. So just
running the dev workflow keeps your local DB in sync with the latest migration
files. No separate command to remember.

## How tracking works

A `_migrations` table records every file that's been applied. The runners
(`scripts/migrate.ts` for local, `apps/api/scripts/migrate.py` for the
container) both share this table — they're equivalent and idempotent.

## Backfill notes

If a migration was applied manually (psql, Supabase MCP) without going through
the runner, the file isn't in `_migrations` and the next runner pass will try
to re-apply it and fail (e.g. `policy already exists`). Backfill once:

```sql
insert into _migrations (filename) values
  ('00X_thing_you_applied_manually.sql')
on conflict (filename) do nothing;
```

Going forward, always apply via `pnpm db:migrate` (locally) or let Render's
preDeployCommand handle it (prod).
