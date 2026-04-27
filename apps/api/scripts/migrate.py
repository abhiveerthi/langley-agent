"""
Apply SQL migrations from packages/db/migrations/ in filename order.

Mirrors scripts/migrate.ts so the API's Docker image can run migrations
during Render's preDeployCommand without needing Node/pnpm/tsx in the
container. Uses psycopg, which is already a runtime dep of the API.

Tracking table `_migrations` is created on first run; rerun is a no-op.
Each file runs in its own transaction — a failure rolls that one back
and aborts the run with exit 1 so the caller (Render) can hold the deploy.

Resolves the migrations dir relative to this file so it works the same
locally (`python apps/api/scripts/migrate.py`) and inside the Render
container (where /app/scripts/migrate.py + /app/packages/ are both
present courtesy of the Dockerfile COPY steps).

DATABASE_URL is required. The shape is the same as for the rest of the
API — a Postgres URL pointing at local Supabase (54322) for dev or the
prod cluster on Render.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1

    # Resolve packages/db/migrations from this file. Two layouts to support:
    #   - dev:        apps/api/scripts/migrate.py → repo-root is parents[3]
    #   - container:  /app/scripts/migrate.py    → /app is parents[1]
    # The Dockerfile copies `packages/` to /app/packages, so the second
    # form lands at /app/packages/db/migrations.
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "packages" / "db" / "migrations",  # dev (repo root)
        here.parents[1] / "packages" / "db" / "migrations",  # container (/app)
    ]
    migrations_dir = next((p for p in candidates if p.is_dir()), None)
    if migrations_dir is None:
        print(
            "Could not find packages/db/migrations. Tried: "
            + ", ".join(str(p) for p in candidates),
            file=sys.stderr,
        )
        return 1

    files = sorted(p for p in migrations_dir.iterdir() if p.suffix == ".sql")
    if not files:
        print(f"No .sql files in {migrations_dir}.")
        return 0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists _migrations (
                    filename text primary key,
                    applied_at timestamptz not null default now()
                );
                """
            )
            conn.commit()

            cur.execute("select filename from _migrations")
            applied = {row[0] for row in cur.fetchall()}

        ran = 0
        for path in files:
            name = path.name
            if name in applied:
                print(f"  skip  {name}")
                continue
            sql = path.read_text(encoding="utf-8")
            print(f"  apply {name} ... ", end="", flush=True)
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "insert into _migrations (filename) values (%s)", (name,)
                    )
                conn.commit()
                print("ok")
                ran += 1
            except Exception as e:  # noqa: BLE001 — surface any DB error
                conn.rollback()
                print("failed")
                print(e, file=sys.stderr)
                return 1

    print("Nothing to apply." if ran == 0 else f"Applied {ran} migration(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
