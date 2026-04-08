from fastapi import APIRouter, Depends
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
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("threads")
        .select("*, messages(id, role, content, created_at)")
        .eq("org_id", user.org_id)
        .eq("status", "active")
        .order("updated_at", desc=True)
        .limit(50)
        .execute()
    )
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
