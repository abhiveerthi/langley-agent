"""API router for the video clipper workflow."""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from app.dependencies import get_current_user, CurrentUser

router = APIRouter(tags=["clipper"])


class ClipRequest(BaseModel):
    video_url: str


class ClipResponse(BaseModel):
    status: str
    message: str


class ClipResult(BaseModel):
    clips: list[dict]
    storage_urls: list[str]


# In-memory job store (swap for Redis/DB in production)
_jobs: dict[str, dict] = {}


def _run_clipper_job(job_id: str, video_url: str):
    """Run clipper in background thread."""
    from packages.clipper.workflow import run_clipper

    try:
        _jobs[job_id]["status"] = "running"
        result = run_clipper(video_url)
        _jobs[job_id]["status"] = "complete"
        _jobs[job_id]["result"] = {
            "clips": result.get("clips", []),
            "storage_urls": result.get("storage_urls", []),
        }
    except Exception as e:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(e)


@router.post("/clipper/run", response_model=ClipResponse)
async def run_clipper_endpoint(
    body: ClipRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    """Start a clipper job for a YouTube video URL."""
    import uuid

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued", "video_url": body.video_url, "user_id": user.id}
    background_tasks.add_task(_run_clipper_job, job_id, body.video_url)

    return ClipResponse(status="queued", message=f"Job {job_id} started")


@router.get("/clipper/jobs")
async def list_jobs(user: CurrentUser = Depends(get_current_user)):
    """List all clipper jobs for the current user."""
    user_jobs = {k: v for k, v in _jobs.items() if v.get("user_id") == user.id}
    return user_jobs


@router.get("/clipper/jobs/{job_id}")
async def get_job(job_id: str, user: CurrentUser = Depends(get_current_user)):
    """Get status and results for a clipper job."""
    job = _jobs.get(job_id)
    if not job or job.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
