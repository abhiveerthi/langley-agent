#!/usr/bin/env python3
"""Drive the CM draft-reply flow end-to-end and dump every SSE event so we
can see if waiting_approval fires correctly when the graph pauses at the
approval gate."""
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


def stream(token: str, message: str):
    with httpx.stream(
        "POST",
        f"{API}/api/chat/stream",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": message, "agent_slug": "community-manager"},
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                print(f"[malformed] {payload[:200]}")
                continue
            et = ev.get("type")
            data = ev.get("data") or {}
            if et == "token":
                print(f"[token] {data.get('content', '')[:120]!r}")
            elif et in {"tool_call_start", "tool_call_end"}:
                print(f"[{et}] tool={data.get('tool')} status={data.get('status')}")
            elif et == "waiting_approval":
                print(f"[waiting_approval] approval_id={data.get('approval_id')} action={data.get('action_type')}")
                print(f"  preview: {data.get('preview')}")
                print(f"  payload keys: {list((data.get('payload') or {}).keys())}")
            elif et == "done":
                print("[done]")
            else:
                print(f"[{et}] {json.dumps(data)[:160]}")


def approve(token: str, approval_id: str):
    with httpx.stream(
        "POST",
        f"{API}/api/approvals/{approval_id}/approve",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            et = ev.get("type")
            data = ev.get("data") or {}
            if et == "token":
                print(f"[token] {data.get('content', '')[:200]!r}")
            elif et == "approval_recorded":
                print(f"[approval_recorded] {json.dumps(data)[:160]}")
            elif et == "done":
                print("[done]")
            else:
                print(f"[{et}] {json.dumps(data)[:160]}")


def main() -> int:
    token = sign_in()
    print("Signed in.\n")

    print("=" * 60)
    msg = "Draft a reply to SeanRowan-r8f's comment on the Rolling Sky video"
    print(f"USER: {msg}")
    print("=" * 60)
    # Capture the approval_id by re-streaming and parsing
    approval_id: str | None = None
    with httpx.stream(
        "POST",
        f"{API}/api/chat/stream",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": msg, "agent_slug": "community-manager"},
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            et = ev.get("type")
            data = ev.get("data") or {}
            if et == "token":
                print(f"[token] {data.get('content', '')[:200]!r}")
            elif et == "waiting_approval":
                approval_id = data.get("approval_id")
                print(f"[waiting_approval] approval_id={approval_id}")
            else:
                print(f"[{et}] {json.dumps(data)[:160]}")
    if not approval_id:
        print("ERROR: no approval_id captured")
        return 1

    print()
    print("=" * 60)
    print(f"USER (simulated approve): approving {approval_id}")
    print("=" * 60)
    approve(token, approval_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
