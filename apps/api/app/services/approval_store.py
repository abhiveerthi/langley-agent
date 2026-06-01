"""
Approval storage layer.

Two implementations share one protocol so the API routers stay storage-agnostic:

  - InMemoryApprovalStore — process-local dict, used when Supabase isn't
    configured (local dev without Supabase URL). State survives across
    requests within a single uvicorn worker, and disappears on restart.

  - SupabaseApprovalStore — writes to the `approvals` table defined in
    packages/db/migrations/001_core.sql. Used automatically when
    SUPABASE_URL + SUPABASE_SERVICE_KEY are set.

The record shape matches the Postgres schema exactly so the two backends are
wire-compatible. Selector lives at the bottom: `get_approval_store()`.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalStore(Protocol):
    async def create(self, *, org_id: str, thread_id: str,
                     requested_by_agent: str, action_type: str,
                     action_payload: dict, preview: str,
                     chain: list[str] | None = None,
                     step_index: int = 0,
                     approver_role: str | None = None) -> dict: ...

    async def get(self, approval_id: str) -> dict | None: ...

    async def list_pending(self, org_id: str) -> list[dict]: ...

    async def update_status(self, approval_id: str, *, status: str,
                            reviewed_by: str | None = None) -> dict | None: ...


class InMemoryApprovalStore:
    """Process-local store for dev use. Singleton: reuse across requests."""

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    async def create(self, *, org_id, thread_id, requested_by_agent,
                     action_type, action_payload, preview,
                     chain=None, step_index=0, approver_role=None):
        row = {
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "thread_id": thread_id,
            "requested_by_agent": requested_by_agent,
            "action_type": action_type,
            "action_payload": action_payload,
            "preview": preview,
            "status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
            # Multi-step approval chain (migration 019). `chain` is the ordered
            # list of role labels; `step_index` is which one this row is;
            # `approver_role` mirrors chain[step_index] for convenience.
            "chain": list(chain) if chain else None,
            "step_index": step_index,
            "approver_role": approver_role,
            "created_at": _utcnow_iso(),
        }
        self._rows[row["id"]] = row
        return row

    async def get(self, approval_id):
        return self._rows.get(approval_id)

    async def list_pending(self, org_id):
        return [
            r for r in self._rows.values()
            if r["org_id"] == org_id and r["status"] == "pending"
        ]

    async def update_status(self, approval_id, *, status, reviewed_by=None):
        row = self._rows.get(approval_id)
        if not row:
            return None
        row["status"] = status
        row["reviewed_by"] = reviewed_by
        row["reviewed_at"] = _utcnow_iso()
        return row


class SupabaseApprovalStore:
    """Supabase-backed store. Schema: migrations/001_core.sql `approvals`."""

    def __init__(self, client) -> None:
        self._client = client

    async def create(self, *, org_id, thread_id, requested_by_agent,
                     action_type, action_payload, preview,
                     chain=None, step_index=0, approver_role=None):
        payload: dict = {
            "org_id": org_id,
            "thread_id": thread_id,
            "requested_by_agent": requested_by_agent,
            "action_type": action_type,
            "action_payload": action_payload,
            "preview": preview,
            "status": "pending",
        }
        # Only send chain columns when a real multi-step chain is in play, so
        # the single-step default insert is byte-identical to the legacy one.
        # (The DB columns default to NULL/0 for omitted single-step rows.)
        if chain is not None:
            payload["chain"] = list(chain)
            payload["step_index"] = step_index
            payload["approver_role"] = approver_role
        result = (
            self._client.table("approvals")
            .insert(payload)
            .execute()
        )
        return result.data[0]

    async def get(self, approval_id):
        result = (
            self._client.table("approvals")
            .select("*")
            .eq("id", approval_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    async def list_pending(self, org_id):
        result = (
            self._client.table("approvals")
            .select("*")
            .eq("org_id", org_id)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .execute()
        )
        return result.data

    async def update_status(self, approval_id, *, status, reviewed_by=None):
        result = (
            self._client.table("approvals")
            .update({
                "status": status,
                "reviewed_by": reviewed_by,
                "reviewed_at": _utcnow_iso(),
            })
            .eq("id", approval_id)
            .execute()
        )
        return result.data[0] if result.data else None


# ── Singleton selector ────────────────────────────────────────────────────
# One instance per process, chosen at first use. Good enough for dev; when we
# wire real auth/tenancy (backlog item B) we'll formalize this as a FastAPI
# dependency.
_store: ApprovalStore | None = None


def get_approval_store() -> ApprovalStore:
    global _store
    if _store is not None:
        return _store

    supabase_url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if supabase_url and supabase_key:
        from supabase import create_client
        client = create_client(supabase_url, supabase_key)
        _store = SupabaseApprovalStore(client)
    else:
        _store = InMemoryApprovalStore()
    return _store
