"""
Tasks API — backs the Monday-style Kanban workspace at `/app/tasks` plus
the per-deal task list on the Brand Manager dashboard.

Endpoints:
  GET    /api/tasks                 — list (filterable by status / agent / deal)
  POST   /api/tasks                 — create
  PATCH  /api/tasks/{id}            — update (status / position / fields)
  POST   /api/tasks/{id}/cancel     — soft-cancel (status='cancelled')
  DELETE /api/tasks/{id}            — hard-delete
  GET    /api/workspace/statuses    — per-org Kanban column list (defaults
                                      to ["todo","in_progress","blocked","done"])

The `position` int is what makes drag-and-drop ordering work — the
frontend reorders within a column by issuing PATCHes with new position
values. We don't try to renumber other tasks server-side; we trust the
client's batched updates to keep the order consistent.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase

router = APIRouter(tags=["tasks"])


# ── Default column set ────────────────────────────────────────────────────
# Mirrors the orgs.task_statuses migration default. Orgs that haven't
# customized still see this set; future custom-statuses UI updates the
# orgs row directly.
_DEFAULT_TASK_STATUSES: list[str] = ["todo", "in_progress", "blocked", "done"]


# ── Schemas ───────────────────────────────────────────────────────────────
class CreateTaskRequest(BaseModel):
    title: str
    description: Optional[str] = None
    project_id: Optional[str] = None
    agent_id: Optional[str] = None
    deal_id: Optional[str] = None
    status: str = "todo"
    priority: str = "medium"
    due_at: Optional[str] = None
    # Position within the destination column. Frontend computes this when
    # creating from a particular column; default 0 puts new tasks at the top.
    position: int = 0


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    agent_id: Optional[str] = None
    project_id: Optional[str] = None
    deal_id: Optional[str] = None
    position: Optional[int] = None
    due_at: Optional[str] = None
    # Allow explicit clearing of optional fields. Frontend sets
    # `clear: ["deal_id"]` etc. when a user un-links a task — distinct
    # from "don't touch this field" (omit) vs "set to null" (clear).
    clear: list[str] = Field(default_factory=list)


# ── Endpoints ─────────────────────────────────────────────────────────────
@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    deal_id: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """List tasks scoped to the caller's org. Filters compose; ordering is
    `(status, position, created_at desc)` which matches what the Kanban
    needs to render columns in the right order without re-sorting client-side."""
    query = (
        supabase.table("tasks")
        .select("*, agents(name, slug, icon)")
        .eq("org_id", user.org_id)
    )
    if status:
        query = query.eq("status", status)
    if priority:
        query = query.eq("priority", priority)
    if agent_id:
        query = query.eq("agent_id", agent_id)
    if project_id:
        query = query.eq("project_id", project_id)
    if deal_id:
        query = query.eq("deal_id", deal_id)
    # Postgrest accepts repeated .order() to compose a multi-key sort.
    result = (
        query
        .order("position", desc=False)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    return result.data


@router.post("/tasks")
async def create_task(
    body: CreateTaskRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    payload = {
        "org_id": user.org_id,
        "created_by": user.id,
        "title": body.title,
        "description": body.description,
        "project_id": body.project_id,
        "agent_id": body.agent_id,
        "deal_id": body.deal_id,
        "status": body.status,
        "priority": body.priority,
        "due_at": body.due_at,
        "position": body.position,
    }
    result = supabase.table("tasks").insert(payload).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Insert returned no row")
    return result.data[0]


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str,
    body: UpdateTaskRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Drag-and-drop fires this with `{status, position}`. Field edits send
    whichever fields changed. `clear` explicitly nulls out optional FKs so
    a user can un-link a task from a deal without sending null (which would
    be ambiguous with "don't update")."""
    updates: dict = body.model_dump(exclude_none=True, exclude={"clear"})
    for key in body.clear:
        if key in {"deal_id", "agent_id", "project_id", "due_at"}:
            updates[key] = None

    if not updates:
        # Defensive — nothing to do; return current row so the FE doesn't
        # have to handle a special "no-op" response shape.
        result = (
            supabase.table("tasks")
            .select("*")
            .eq("id", task_id)
            .eq("org_id", user.org_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Task not found")
        return result.data[0]

    result = (
        supabase.table("tasks")
        .update(updates)
        .eq("id", task_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Task not found")
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
    if not result.data:
        raise HTTPException(status_code=404, detail="Task not found")
    return result.data[0]


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Hard-delete. Cancel is the soft path (keeps audit trail); delete
    removes the row entirely — used when the user just wants the task off
    the board permanently."""
    result = (
        supabase.table("tasks")
        .delete()
        .eq("id", task_id)
        .eq("org_id", user.org_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": task_id}


@router.get("/workspace/statuses")
async def list_statuses(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Per-org Kanban column list. Returns the org's `task_statuses` jsonb
    array, falling back to the standard set when the column is missing
    (pre-migration env) or empty. The custom-statuses settings UI is a
    follow-up — for now this endpoint just exposes the schema default."""
    try:
        result = (
            supabase.table("orgs")
            .select("task_statuses")
            .eq("id", user.org_id)
            .limit(1)
            .execute()
        )
    except Exception:
        return {"statuses": _DEFAULT_TASK_STATUSES}

    if not result.data:
        return {"statuses": _DEFAULT_TASK_STATUSES}

    statuses = result.data[0].get("task_statuses")
    if not isinstance(statuses, list) or not statuses:
        return {"statuses": _DEFAULT_TASK_STATUSES}
    return {"statuses": statuses}
