from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import (
    settings,
    current_environment,
    database_url_for_environment,
    BACKEND_DIR,
)
from app.core.timezone import sao_paulo_utc_iso
from app.db.session import get_db
from app.models.agent import LocalAgent
from app.models.automation import Automation
from app.models.file import WorkspaceFile
from app.models.workspace import Workspace

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/api/health")
def api_health_check():
    return {"status": "ok"}


def _safe_db_url(url: str) -> str:
    """Hide credentials before returning a connection string to the UI."""
    if url.startswith("sqlite"):
        return url
    try:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        return f"{scheme}://{rest}"
    except ValueError:
        return url.split("://", 1)[0]


def _database_diagnostic(db: Session) -> dict:
    url = database_url_for_environment()
    info: dict = {"engine": url.split(":", 1)[0], "url": _safe_db_url(url)}
    start = time.perf_counter()
    db.execute(text("SELECT 1"))
    info["status"] = "ok"
    info["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
    if url.startswith("sqlite"):
        try:
            info["journal_mode"] = db.execute(text("PRAGMA journal_mode")).scalar()
        except Exception:
            pass
    return info


def _agent_diagnostic(db: Session) -> dict:
    stale_seconds = max(int(settings.AGENT_POLL_INTERVAL_SECONDS or 5) * 6, 30)
    agent = (
        db.query(LocalAgent)
        .filter(LocalAgent.is_deleted == False)
        .order_by(LocalAgent.last_heartbeat_at.desc(), LocalAgent.id.desc())
        .first()
    )
    if not agent or not agent.last_heartbeat_at:
        return {"status": "not_seen", "message": "Nenhum agente local visto recentemente."}
    age = int((datetime.utcnow() - agent.last_heartbeat_at).total_seconds())
    return {
        "status": "active" if age <= stale_seconds else "stale",
        "agent_name": agent.name,
        "machine_name": agent.machine_name,
        "version": agent.version,
        "last_heartbeat_at": sao_paulo_utc_iso(agent.last_heartbeat_at),
        "age_seconds": age,
        "stale_after_seconds": stale_seconds,
    }


def _chromium_diagnostic() -> dict:
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
    candidates: list[tuple[Path, str]] = []
    if env_path:
        candidates.append((Path(env_path), "env"))
    candidates.append((BACKEND_DIR / "ms-playwright", "bundled"))
    for base, source in candidates:
        try:
            if base.exists():
                builds = sorted(
                    p.name for p in base.iterdir()
                    if p.is_dir() and p.name.lower().startswith("chromium")
                )
                if builds:
                    return {"status": "ok", "source": source, "path": str(base), "builds": builds}
        except OSError:
            continue
    fallback = env_path or str(BACKEND_DIR / "ms-playwright")
    return {"status": "missing", "path": fallback, "builds": []}


def _stats_diagnostic(db: Session) -> dict:
    files_q = db.query(WorkspaceFile).filter(WorkspaceFile.is_deleted == False)
    return {
        "automations": db.query(Automation).filter(Automation.is_deleted == False).count(),
        "workspaces": db.query(Workspace).filter(Workspace.is_deleted == False).count(),
        "files_total": files_q.count(),
        "files_ready": files_q.filter(WorkspaceFile.status == "ready").count(),
        "files_pending": files_q.filter(WorkspaceFile.status.in_(["pending", "uploaded"])).count(),
        "files_error": files_q.filter(
            WorkspaceFile.status.in_(["failed", "manual_review", "pending_retry"])
        ).count(),
    }


@router.get("/api/diagnostics")
def api_diagnostics(db: Session = Depends(get_db)):
    """Real, environment-aware health snapshot consumed by the About tab.

    Each section is isolated so one failing probe never breaks the whole report.
    """
    started = time.perf_counter()
    out: dict = {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "environment": current_environment(),
        "server_time": sao_paulo_utc_iso(datetime.utcnow()),
        "backend": {"status": "ok"},
    }
    sections = (
        ("database", lambda: _database_diagnostic(db)),
        ("agent", lambda: _agent_diagnostic(db)),
        ("chromium", _chromium_diagnostic),
        ("stats", lambda: _stats_diagnostic(db)),
    )
    for key, fn in sections:
        try:
            out[key] = fn()
        except Exception as exc:  # noqa: BLE001 - report, never 500
            out[key] = {"status": "error", "error": str(exc)[:200]}
            out["status"] = "degraded"
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out
