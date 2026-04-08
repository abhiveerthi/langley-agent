from fastapi import APIRouter, Depends
from app.dependencies import get_current_user, CurrentUser, get_supabase
from supabase import Client
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None
    color: str = "#6366F1"
    icon: Optional[str] = None


@router.get("/projects")
async def list_projects(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("projects")
        .select("*, tasks(id, status)")
        .eq("org_id", user.org_id)
        .neq("status", "archived")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.post("/projects")
async def create_project(
    body: CreateProjectRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = supabase.table("projects").insert({
        "org_id": user.org_id,
        "name": body.name,
        "description": body.description,
        "color": body.color,
        "icon": body.icon,
    }).execute()
    return result.data[0]


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    project = (
        supabase.table("projects")
        .select("*")
        .eq("id", project_id)
        .eq("org_id", user.org_id)
        .single()
        .execute()
    )
    tasks = (
        supabase.table("tasks")
        .select("*, agents(name, slug, icon)")
        .eq("project_id", project_id)
        .eq("org_id", user.org_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {**project.data, "tasks": tasks.data}


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    body: dict,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("projects")
        .update(body)
        .eq("id", project_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]


@router.delete("/projects/{project_id}")
async def archive_project(
    project_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("projects")
        .update({"status": "archived"})
        .eq("id", project_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    return result.data[0]
