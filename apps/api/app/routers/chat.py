from typing import Optional

from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_user, CurrentUser, get_supabase
from supabase import Client

router = APIRouter(tags=["chat"])


@router.post("/chat/threads")
async def create_thread(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = supabase.table("threads").insert({
        "org_id": user.org_id,
        "user_id": user.id,
        "status": "active",
    }).execute()
    return result.data[0]


@router.get("/chat/threads")
async def list_threads(
    agent_slug: Optional[str] = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """List active threads for the user's org.

    `agent_slug` filters via the JSON-path on `metadata.agent_slug` so the
    per-agent MiniChat sidebar only sees its own chats. The orchestrator
    stamps that key on every `_ensure_thread_row` upsert (see
    services/graph_orchestrator.py).
    """
    q = (
        supabase.table("threads")
        .select("*, messages(id, role, content, created_at)")
        .eq("org_id", user.org_id)
        .eq("status", "active")
    )
    if agent_slug:
        # PostgREST JSON-path filter — `metadata->>agent_slug` matches the
        # text value stamped by the orchestrator on thread creation.
        q = q.eq("metadata->>agent_slug", agent_slug)
    result = q.order("updated_at", desc=True).limit(50).execute()
    return result.data


@router.get("/chat/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    thread = (
        supabase.table("threads")
        .select("*")
        .eq("id", thread_id)
        .eq("org_id", user.org_id)
        .single()
        .execute()
    )
    messages = (
        supabase.table("messages")
        .select("*")
        .eq("thread_id", thread_id)
        .order("created_at")
        .execute()
    )
    return {**thread.data, "messages": messages.data}


@router.delete("/chat/threads/{thread_id}")
async def archive_thread(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("threads")
        .update({"status": "archived"})
        .eq("id", thread_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]
