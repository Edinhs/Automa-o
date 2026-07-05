from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import reset_current_environment, set_current_environment, settings
from app.routers.deps import get_current_user, require_agent_or_user
from app.services.schedule_runner import start_schedule_runner, stop_schedule_runner

from app.routers import health, auth, users, automations, workspaces, files, logs, reports, schedules, agents, integrations, executions, trash, custom_automations, overview

app = FastAPI(title=settings.APP_NAME)


@app.middleware("http")
async def select_environment(request, call_next):
    token = set_current_environment(request.headers.get("X-App-Environment"))
    try:
        return await call_next(request)
    finally:
        reset_current_environment(token)


@app.on_event("startup")
async def startup_event():
    from app.db.migrate_schedules import run_migrations
    run_migrations()
    start_schedule_runner()


@app.on_event("shutdown")
async def shutdown_event():
    await stop_schedule_runner()

origins = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
protected = [Depends(get_current_user)]
agent_protected = [Depends(require_agent_or_user)]

app.include_router(users.router, prefix="/api/users", tags=["Users"], dependencies=protected)
app.include_router(automations.router, prefix="/api/automations", tags=["Automations"], dependencies=agent_protected)
app.include_router(executions.router, prefix="/api/executions", tags=["Executions"], dependencies=protected)
app.include_router(workspaces.router, prefix="/api/workspaces", tags=["Workspaces"], dependencies=protected)
app.include_router(files.router, prefix="/api/files", tags=["Files"], dependencies=agent_protected)
app.include_router(logs.router, prefix="/api/logs", tags=["Logs"], dependencies=protected)
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"], dependencies=protected)
app.include_router(schedules.router, prefix="/api/schedules", tags=["Schedules"], dependencies=protected)
app.include_router(agents.router, prefix="/api/agents", tags=["Agents"], dependencies=agent_protected)
app.include_router(integrations.router, prefix="/api/integrations", tags=["Integrations"], dependencies=protected)
app.include_router(trash.router, prefix="/api/trash", tags=["Trash"], dependencies=protected)
app.include_router(custom_automations.router, prefix="/api/custom-automations", tags=["Custom Automations"], dependencies=protected)
app.include_router(overview.router, prefix="/api/overview", tags=["Overview"], dependencies=protected)
