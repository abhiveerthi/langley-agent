#!/usr/bin/env python3
"""One-shot helper: create a known test account on local Supabase.

Idempotent — running twice won't error; it will skip rows that already exist
and print the credentials so you can copy/paste into the login page.

Run with:
    apps/api/.venv/bin/python3 scripts/create_test_account.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Load .env so SUPABASE_URL / SERVICE_KEY are visible.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from supabase import create_client  # noqa: E402

EMAIL = "test@marcus.dev"
PASSWORD = "password123"
FULL_NAME = "Test User"
ORG_NAME = "Test Workspace"
ORG_SLUG = "test-workspace"


def main() -> int:
    url = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
    service_key = os.environ["SUPABASE_SERVICE_KEY"]

    if "127.0.0.1" not in url and "localhost" not in url:
        print(f"Refusing to run against non-local Supabase: {url}")
        return 1

    sb = create_client(url, service_key)

    # ── 1. Auth user ────────────────────────────────────────────────────
    existing = sb.auth.admin.list_users()
    user = next((u for u in existing if u.email == EMAIL), None)
    if user:
        print(f"  → auth user already exists: {user.id}")
    else:
        created = sb.auth.admin.create_user({
            "email": EMAIL,
            "password": PASSWORD,
            "email_confirm": True,
            "user_metadata": {"full_name": FULL_NAME},
        })
        user = created.user
        print(f"  → created auth user: {user.id}")

    # ── 2. public.users mirror row ──────────────────────────────────────
    sb.table("users").upsert({
        "id": user.id,
        "email": EMAIL,
        "full_name": FULL_NAME,
    }, on_conflict="id").execute()
    print(f"  → users row upserted")

    # ── 3. Org ──────────────────────────────────────────────────────────
    org_resp = sb.table("orgs").select("id").eq("slug", ORG_SLUG).limit(1).execute()
    if org_resp.data:
        org_id = org_resp.data[0]["id"]
        print(f"  → org already exists: {org_id}")
    else:
        org_resp = sb.table("orgs").insert({
            "name": ORG_NAME,
            "slug": ORG_SLUG,
            "plan": "starter",
        }).execute()
        org_id = org_resp.data[0]["id"]
        print(f"  → created org: {org_id}")

    # ── 4. Membership (owner) ───────────────────────────────────────────
    sb.table("org_members").upsert({
        "org_id": org_id,
        "user_id": user.id,
        "role": "owner",
    }, on_conflict="org_id,user_id").execute()
    print(f"  → org_member upserted (owner)")

    # Intentionally NOT writing an org_profiles row — the blank-profile
    # fallback in load_profile() handles that case so the agent runs cleanly.

    print()
    print("=" * 60)
    print("Test account ready:")
    print(f"  Email:    {EMAIL}")
    print(f"  Password: {PASSWORD}")
    print(f"  Org:      {ORG_NAME} ({org_id})")
    print(f"  Login at: http://localhost:3000/login")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
