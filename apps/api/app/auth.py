"""
Request-scoped tenancy helpers shared by routers that stream agent events.

The Bearer-token auth pattern lives here so `/chat/stream`,
`/approvals/*`, and any future streaming endpoint resolve (org_id,
user_id, supabase) the same way and set the same ContextVars for the
agent tools to read.

Two helpers:

  resolve_user(request)
    Read the Authorization header, validate the token via Supabase,
    look up the user's org membership, and return
    `(org_id, user_id, supabase)`. Falls back to `("dev", "dev", …)`
    when Supabase isn't configured or the token is missing/invalid so
    local development without auth keeps working.

  with_tool_context(gen, *, org_id, user_id, supabase)
    Async-generator wrapper that sets `current_org_id`,
    `current_user_id`, and `current_supabase` ContextVars for the
    lifetime of the stream, then yields through to the underlying
    orchestrator. Agent tools read these to scope queries per-tenant.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from fastapi import Request

from app.config import get_settings
from app.dependencies import get_supabase
from packages.integrations.context import (
    current_org_id,
    current_supabase,
    current_user_id,
)


def resolve_user(request: Request) -> tuple[str, str, Any]:
    """Resolve `(org_id, user_id, supabase)` from the Authorization header.

    Graceful fallback to "dev" defaults so the API still serves local
    development without Supabase configured or without a signed-in user.
    """
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_key):
        return "dev", "dev", None
    # Share the cached service-role client with `Depends(get_supabase)`
    # — same singleton, no extra construction.
    supabase = get_supabase(settings)

    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return "dev", "dev", supabase

    token = auth.split(" ", 1)[1]
    try:
        user_resp = supabase.auth.get_user(token)
        user = getattr(user_resp, "user", None)
        if not user:
            return "dev", "dev", supabase
        membership = (
            supabase.table("org_members")
            .select("org_id")
            .eq("user_id", user.id)
            .limit(1)
            .execute()
        )
        if not membership.data:
            return "dev", user.id, supabase
        return membership.data[0]["org_id"], user.id, supabase
    except Exception:
        return "dev", "dev", supabase


async def with_tool_context(
    gen: AsyncIterator[str],
    *,
    org_id: str,
    user_id: str,
    supabase: Any,
) -> AsyncIterator[str]:
    """Set tenancy ContextVars for the lifetime of an SSE stream."""
    current_org_id.set(org_id)
    current_user_id.set(user_id)
    current_supabase.set(supabase)
    async for event in gen:
        yield event
