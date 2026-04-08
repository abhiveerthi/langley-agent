from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_user, CurrentUser, get_supabase
from supabase import Client
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["tasks"])


class CreateTaskRequest(BaseModel):
    title: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    agent_id: Optional[str] = None
    priority: str = "medium"
    due_at: Optional[str] = None


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    agent_id: Optional[str] = None
    project_id: Optional[str] = None


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    query = supabase.table("tasks").select("*, agents(name, slug, icon)").eq("org_id", user.org_id)
    if status:
        query = query.eq("status", status)
    if priority:
        query = query.eq("priority", priority)
    if agent_id:
        query = query.eq("agent_id", agent_id)
    if project_id:
        query = query.eq("project_id", project_id)
    result = query.order("created_at", desc=True).limit(100).execute()
    return result.data


@router.post("/tasks")
async def create_task(
    body: CreateTaskRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = supabase.table("tasks").insert({
        "org_id": user.org_id,
        "created_by": user.id,
        "title": body.title,
        "description": body.description,
        "project_id": body.project_id,
        "agent_id": body.agent_id,
        "priority": body.priority,
        "due_at": body.due_at,
    }).execute()
    return result.data[0]


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str,
    body: UpdateTaskRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    updates = body.model_dump(exclude_none=True)
    result = (
        supabase.table("tasks")
        .update(updates)
        .eq("id", task_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("tasks")
        .update({"status": "cancelled"})
        .eq("id", task_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]
