#!/usr/bin/env tsx
/**
 * Apply all SQL migrations in packages/db/migrations/ to DATABASE_URL.
 *
 * Runs in filename order and records applied files in a `_migrations` table
 * so reruns skip anything already applied. Uses `pg` (which accepts the
 * Supabase pooler URL on IPv4, unlike the direct `db.*` host).
 *
 * Usage:
 *   pnpm db:migrate
 */
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { Client } from "pg";
import { config } from "dotenv";

config({ path: resolve(process.cwd(), ".env") });

const DATABASE_URL = process.env.DATABASE_URL;
if (!DATABASE_URL) {
  console.error("DATABASE_URL is not set. Put it in .env at the repo root.");
  process.exit(1);
}

const MIGRATIONS_DIR = resolve(process.cwd(), "packages/db/migrations");

async function main() {
  const client = new Client({ connectionString: DATABASE_URL });
  await client.connect();

  await client.query(`
    create table if not exists _migrations (
      filename text primary key,
      applied_at timestamptz not null default now()
    );
  `);

  const applied = new Set<string>(
    (await client.query<{ filename: string }>("select filename from _migrations")).rows.map(
      (r) => r.filename
    )
  );

  const files = readdirSync(MIGRATIONS_DIR)
    .filter((f) => f.endsWith(".sql"))
    .sort();

  let ran = 0;
  for (const file of files) {
    if (applied.has(file)) {
      console.log(`  skip  ${file}`);
      continue;
    }
    const sql = readFileSync(resolve(MIGRATIONS_DIR, file), "utf8");
    process.stdout.write(`  apply ${file} ... `);
    try {
      await client.query("begin");
      await client.query(sql);
      await client.query("insert into _migrations (filename) values ($1)", [file]);
      await client.query("commit");
      ran++;
      console.log("ok");
    } catch (err) {
      await client.query("rollback");
      console.error("failed");
      console.error(err);
      process.exit(1);
    }
  }

  await client.end();
  console.log(ran === 0 ? "Nothing to apply." : `Applied ${ran} migration(s).`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
