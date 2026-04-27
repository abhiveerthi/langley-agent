from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.routers import chat, stream, agents, tasks, projects, runs, approvals, notifications, dashboard, integrations, publisher, profile, strategist, brand_manager, storage, slack_events, slack_interactive
from app.services.graph_orchestrator import close_checkpointer, init_checkpointer

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan — wires the LangGraph checkpointer to Postgres on startup
    and tears it down on shutdown. Without this, the orchestrator falls back
    to an in-memory checkpointer that loses paused approvals on restart."""
    await init_checkpointer()
    yield
    await close_checkpointer()


app = FastAPI(
    title="AgentOS API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


app.include_router(chat.router, prefix="/api")
app.include_router(stream.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(approvals.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(publisher.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(strategist.router, prefix="/api")
app.include_router(brand_manager.router, prefix="/api")
app.include_router(storage.router, prefix="/api")
app.include_router(slack_events.router, prefix="/api")
app.include_router(slack_interactive.router, prefix="/api")
