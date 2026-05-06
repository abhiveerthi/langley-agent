#!/usr/bin/env python3
"""Loop-test the community manager as the local test user.

Signs in to local Supabase, hits /api/chat/stream against the running API,
streams the SSE response, prints the final assistant message. Used while
iterating on CM bugs — run this, read the output, fix, repeat.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

EMAIL = "test@marcus.dev"
PASSWORD = "password123"
API = os.environ.get("NEXT_PUBLIC_API_URL", "http://localhost:8000")
SUPABASE_URL = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
SUPABASE_ANON = os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"]


def sign_in() -> str:
    resp = httpx.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": SUPABASE_ANON, "Content-Type": "application/json"},
        json={"email": EMAIL, "password": PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def ask_cm(token: str, message: str) -> dict:
    """POST to /chat/stream and collect the SSE events."""
    events: list[dict] = []
    with httpx.stream(
        "POST",
        f"{API}/api/chat/stream",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": message, "agent_slug": "community-manager"},
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        thread_id = resp.headers.get("x-thread-id", "?")
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                events.append({"raw": payload})

    final_text_parts: list[str] = []
    for ev in events:
        et = ev.get("type")
        if et in {"message", "ai_message", "assistant_message", "final"}:
            content = ev.get("content") or ev.get("text") or ev.get("message")
            if isinstance(content, str):
                final_text_parts.append(content)
        elif et == "token":
            tok = ev.get("token") or ev.get("delta") or ""
            if tok:
                final_text_parts.append(tok)
    return {
        "thread_id": thread_id,
        "events": events,
        "final": "".join(final_text_parts),
    }


def main() -> int:
    print(f"Signing in as {EMAIL}…")
    token = sign_in()
    print(f"  → got JWT (len={len(token)})\n")

    prompts = [
        "How is my audience doing?",
        "Triage my recent comments",
        "What are people saying about my latest video?",
        "Look up the channel @MrBeast — is that a VIP?",
    ]
    for p in prompts:
        print("=" * 70)
        print(f"USER: {p}")
        print("=" * 70)
        result = ask_cm(token, p)
        print(f"thread_id: {result['thread_id']}")
        print(f"events: {len(result['events'])}")
        if result["final"]:
            print("\nFINAL TEXT:\n" + result["final"][:2000])
        else:
            print("\n(no text — dumping last 5 events)")
            for ev in result["events"][-5:]:
                print(json.dumps(ev, indent=2)[:500])
        print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code} {e.response.text[:500]}")
        sys.exit(1)
