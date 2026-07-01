from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.timezone import sao_paulo_utc_iso
from app.core.config import settings
from app.db.session import get_db
from app.models.agent import AgentTask, LocalAgent
from app.models.automation import Automation
from app.models.execution import ExecutionLog
from app.models.file import WorkspaceFile
from app.models.user import User
from app.models.workspace import Workspace
from app.routers.deps import require_agent_or_user
from app.services.audit import create_log
from app.services.automation_staging import enabled_extensions_from_config, normalize_folder_path

router = APIRouter()

AUTOMATION_TASK_TYPES = {
    "upload_files_to_workspace",
    "monitor_workspace_files_status",
    "convert_and_retry_file",
}
ACTIVE_TASK_STATUSES = {"pending", "running"}
CANCELLABLE_TASK_STATUSES = {"pending", "running"}
AGENT_HEARTBEAT_STALE_SECONDS = max(int(settings.AGENT_POLL_INTERVAL_SECONDS or 5) * 6, 30)

AUTOMATION_FIELDS = {
    "name",
    "description",
    "type",
    "status",
    "folder_path",
    "temp_folder_path",
    "workspace_id",
    "batch_size",
    "batch_interval_seconds",
    "monitoring_timeout_minutes",
    "monitor_interval_seconds",
    "max_retries",
    "keep_temp_on_error",
    "convert_to_pdf_on_error",
    "full_execution",
    "config_json",
}


def automation_payload(data: dict) -> dict:
    data = data or {}
    config = data.get("config") or {}
    if "file_types" in data:
        config["file_types"] = data.get("file_types")
    if data.get("playwright_mode"):
        config["playwright_mode"] = data.get("playwright_mode")
    if data.get("monitor_only") is not None:
        config["monitor_only"] = data.get("monitor_only")

    clean = {
        "name": data.get("name"),
        "description": data.get("description"),
        "type": data.get("type") or data.get("automation_type") or "folder_monitoring",
        "status": data.get("status") or ("active" if data.get("activate_on_finish") else "active"),
        "folder_path": normalize_folder_path(data.get("folder_path")),
        "temp_folder_path": normalize_folder_path(data.get("temp_folder_path")),
        "workspace_id": data.get("workspace_id"),
        "batch_size": data.get("batch_size"),
        "batch_interval_seconds": data.get("batch_interval_seconds"),
        "monitoring_timeout_minutes": data.get("monitoring_timeout_minutes"),
        "monitor_interval_seconds": data.get("monitor_interval_seconds") or settings.DEFAULT_MONITOR_INTERVAL_SECONDS,
        "max_retries": data.get("max_retries") or data.get("max_attempts"),
        "keep_temp_on_error": data.get("keep_temp_on_error"),
        "convert_to_pdf_on_error": data.get("convert_to_pdf_on_error") if "convert_to_pdf_on_error" in data else data.get("convert_to_pdf"),
        "full_execution": data.get("full_execution"),
        "config_json": data.get("config_json") or (json.dumps(config, ensure_ascii=False) if config else None),
    }
    return {key: value for key, value in clean.items() if key in AUTOMATION_FIELDS and value is not None}


def task_payload(task: AgentTask) -> dict:
    if not task.payload_json:
        return {}
    try:
        value = json.loads(task.payload_json)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def safe_int(value) -> int | None:
    if value in [None, ""]:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def automation_config(aut: Automation) -> dict:
    if not aut.config_json:
        return {}
    try:
        value = json.loads(aut.config_json)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def save_automation_config(aut: Automation, config: dict) -> None:
    aut.config_json = json.dumps(config, ensure_ascii=False)


def active_user_by_id(db: Session, user_id: int | None) -> User | None:
    if not user_id:
        return None
    return (
        db.query(User)
        .filter(User.id == user_id, User.is_deleted == False, User.status == "active")
        .first()
    )


def fallback_session_user(db: Session) -> tuple[int | None, str | None]:
    connected_user = (
        db.query(User)
        .filter(
            User.is_deleted == False,
            User.status == "active",
            (User.playground_connected == True) | (User.playground_session_path.isnot(None)),
        )
        .order_by(User.id.asc())
        .first()
    )
    if connected_user:
        return connected_user.id, "connected_user"

    admin_user = (
        db.query(User)
        .filter(User.is_deleted == False, User.status == "active", User.role == "admin")
        .order_by(User.id.asc())
        .first()
    )
    if admin_user:
        return admin_user.id, "active_admin"
    return None, None


def resolve_session_user_id(
    *,
    db: Session,
    aut: Automation,
    workspace: Workspace,
    config: dict,
    current_user: User | None = None,
) -> tuple[int, str]:
    if current_user:
        return current_user.id, "authenticated_user"

    config_user_id = safe_int(config.get("playground_user_id"))
    if config_user_id:
        if active_user_by_id(db, config_user_id):
            return config_user_id, "automation_config"
        raise HTTPException(400, f"Usuario Playground salvo na automacao nao existe ou esta inativo: {config_user_id}")

    owner_user_id = safe_int(workspace.owner_user_id)
    if owner_user_id:
        if active_user_by_id(db, owner_user_id):
            return owner_user_id, "workspace_owner"
        raise HTTPException(400, f"Dono do workspace nao existe ou esta inativo: {owner_user_id}")

    fallback_user_id, fallback_source = fallback_session_user(db)
    if fallback_user_id:
        return fallback_user_id, fallback_source or "fallback_user"

    raise HTTPException(
        400,
        "Nenhum usuario de sessao Playground encontrado para esta automacao. "
        "Conecte o Playground com um usuario real antes de iniciar ou agendar.",
    )


def user_from_actor(actor) -> User | None:
    return actor if isinstance(actor, User) else None


def task_automation_id(task: AgentTask) -> int | None:
    value = task_payload(task).get("automation_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def latest_agent_status(db: Session) -> dict:
    agent = (
        db.query(LocalAgent)
        .filter(LocalAgent.is_deleted == False)
        .order_by(LocalAgent.last_heartbeat_at.desc(), LocalAgent.id.desc())
        .first()
    )
    if not agent or not agent.last_heartbeat_at:
        return {"status": "not_seen", "message": "Nenhum agente local ativo foi visto recentemente."}
    age_seconds = int((datetime.utcnow() - agent.last_heartbeat_at).total_seconds())
    if age_seconds > AGENT_HEARTBEAT_STALE_SECONDS:
        return {
            "status": "stale",
            "agent_id": agent.id,
            "agent_name": agent.name,
            "last_heartbeat_at": sao_paulo_utc_iso(agent.last_heartbeat_at),
            "age_seconds": age_seconds,
            "message": "Agente local sem heartbeat recente; a task ficara aguardando polling.",
        }
    return {
        "status": "active",
        "agent_id": agent.id,
        "agent_name": agent.name,
        "last_heartbeat_at": sao_paulo_utc_iso(agent.last_heartbeat_at),
        "age_seconds": age_seconds,
        "message": "Agente local ativo.",
    }


def automation_tasks(db: Session, automation_id: int, statuses: Iterable[str] | None = None) -> list[AgentTask]:
    query = db.query(AgentTask).filter(
        AgentTask.is_deleted == False,
        AgentTask.task_type.in_(AUTOMATION_TASK_TYPES),
    )
    if statuses is not None:
        query = query.filter(AgentTask.status.in_(list(statuses)))
    return [task for task in query.all() if task_automation_id(task) == automation_id]


def active_automation_tasks(db: Session, automation_id: int) -> list[AgentTask]:
    return automation_tasks(db, automation_id, ACTIVE_TASK_STATUSES)


def cancel_automation_tasks(db: Session, automation_id: int, reason: str) -> int:
    cancelled = 0
    for task in automation_tasks(db, automation_id, CANCELLABLE_TASK_STATUSES):
        task.status = "cancelled"
        task.completed_at = task.completed_at or datetime.utcnow()
        task.error_message = reason
        cancelled += 1
        create_log(
            db,
            "warning",
            reason,
            "agent_task",
            task.id,
            task_id=task.id,
            automation_id=automation_id,
            metadata={"task_type": task.task_type},
        )
    if cancelled:
        db.commit()
    return cancelled


def automation_out(automation: Automation) -> dict:
    try:
        config = json.loads(automation.config_json) if automation.config_json else {}
    except Exception:
        config = {}
    return {
        "id": automation.id,
        "name": automation.name,
        "description": automation.description,
        "type": automation.type,
        "automation_type": automation.type,
        "status": automation.status,
        "folder_path": automation.folder_path,
        "temp_folder_path": automation.temp_folder_path,
        "workspace_id": automation.workspace_id,
        "batch_size": automation.batch_size,
        "batch_interval_seconds": automation.batch_interval_seconds,
        "monitoring_timeout_minutes": automation.monitoring_timeout_minutes,
        "monitor_interval_seconds": automation.monitor_interval_seconds,
        "max_retries": automation.max_retries,
        "max_attempts": automation.max_retries,
        "keep_temp_on_error": automation.keep_temp_on_error,
        "convert_to_pdf_on_error": automation.convert_to_pdf_on_error,
        "convert_to_pdf": automation.convert_to_pdf_on_error,
        "full_execution": bool(automation.full_execution),
        "file_types": config.get("file_types") if isinstance(config.get("file_types"), list) else [],
        "playwright_mode": config.get("playwright_mode"),
        "monitor_only": config.get("monitor_only"),
        "config": config,
        "config_json": automation.config_json,
        "archived_at": sao_paulo_utc_iso(automation.archived_at),
        "is_deleted": automation.is_deleted,
        "created_at": sao_paulo_utc_iso(automation.created_at),
        "updated_at": sao_paulo_utc_iso(automation.updated_at),
    }


def execution_log_out(log: ExecutionLog) -> dict:
    return {
        "id": log.id,
        "level": log.level,
        "message": log.message,
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "automation_id": log.automation_id,
        "file_id": log.file_id,
        "task_id": log.task_id,
        "user_id": log.user_id,
        "metadata_json": log.metadata_json,
        "created_at": sao_paulo_utc_iso(log.created_at),
    }


@router.get("")
def list_automations(db: Session = Depends(get_db)):
    return [automation_out(aut) for aut in db.query(Automation).filter(Automation.is_deleted == False).all()]


@router.post("")
def create_automation(data: dict, db: Session = Depends(get_db)):
    clean = automation_payload(data)
    if not clean.get("name"):
        raise HTTPException(422, "Automation name is required")
    aut = Automation(**clean)
    db.add(aut)
    db.commit()
    db.refresh(aut)
    create_log(db, "info", f"Automation created: {aut.name}", "automation", aut.id, automation_id=aut.id)
    return automation_out(aut)


@router.get("/{id}/logs")
def get_automation_logs(id: int, limit: int = 100, db: Session = Depends(get_db)):
    aut = db.query(Automation).filter(Automation.id == id, Automation.is_deleted == False).first()
    if not aut:
        raise HTTPException(404)
    safe_limit = min(max(limit, 1), 500)
    return [
        execution_log_out(log)
        for log in db.query(ExecutionLog)
        .filter(ExecutionLog.automation_id == id)
        .order_by(ExecutionLog.created_at.desc())
        .limit(safe_limit)
        .all()
    ]


@router.get("/{id}")
def get_automation(id: int, db: Session = Depends(get_db)):
    aut = db.query(Automation).filter(Automation.id == id, Automation.is_deleted == False).first()
    if not aut:
        raise HTTPException(404)
    return automation_out(aut)


@router.put("/{id}")
def update_automation(id: int, data: dict, db: Session = Depends(get_db)):
    aut = db.query(Automation).filter(Automation.id == id, Automation.is_deleted == False).first()
    if not aut:
        raise HTTPException(404)
    for key, value in automation_payload(data).items():
        setattr(aut, key, value)
    db.commit()
    db.refresh(aut)
    return automation_out(aut)


@router.put("/{id}/status")
def update_automation_status(id: int, data: dict, db: Session = Depends(get_db)):
    aut = db.query(Automation).filter(Automation.id == id, Automation.is_deleted == False).first()
    if not aut:
        raise HTTPException(404)
    aut.status = data.get("status") or aut.status
    db.commit()
    db.refresh(aut)
    create_log(db, "info", f"Automation status updated: {aut.status}", "automation", aut.id, automation_id=aut.id)
    return automation_out(aut)


@router.post("/{id}/resolve-errors")
def resolve_automation_errors(id: int, db: Session = Depends(get_db)):
    aut = db.query(Automation).filter(Automation.id == id, Automation.is_deleted == False).first()
    if not aut:
        raise HTTPException(404)
    error_files = db.query(WorkspaceFile).filter(
        WorkspaceFile.automation_id == aut.id,
        WorkspaceFile.is_deleted == False,
        WorkspaceFile.status.in_(["manual_review", "failed"]),
    ).all()
    now = datetime.utcnow()
    for f in error_files:
        f.status = "resolved"
        f.playground_status = "Resolved"
        if not f.ready_at:
            f.ready_at = now
    # Acao manual "Resolvido": resolve os erros E devolve a automacao para ATIVA
    # (e nao "completed"), para o usuario poder reusa-la/monitorar de novo.
    aut.status = "active"
    db.commit()
    create_log(
        db,
        "info",
        f"Resolved {len(error_files)} error file(s) for automation {aut.name}; status set to active.",
        "automation",
        aut.id,
        automation_id=aut.id,
    )
    db.refresh(aut)
    return {"status": aut.status, "resolved": len(error_files), "automation_id": aut.id}


@router.delete("/{id}")
def delete_automation(id: int, db: Session = Depends(get_db)):
    aut = db.query(Automation).filter(Automation.id == id, Automation.is_deleted == False).first()
    if not aut:
        raise HTTPException(404)
    cancelled = cancel_automation_tasks(db, aut.id, "Automation deleted; pending/running tasks cancelled.")
    aut.status = "deleted"
    aut.is_deleted = True
    aut.deleted_at = datetime.utcnow()
    db.commit()
    create_log(db, "warning", "Automation deleted", "automation", aut.id, automation_id=aut.id, metadata={"cancelled_tasks": cancelled})
    return {"status": "deleted", "cancelled_tasks": cancelled}


@router.post("/{id}/actions")
def action_automation(
    id: int,
    action_data: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_agent_or_user),
):
    action = action_data.get("action")
    return run_automation_action(id, action, action_data, db, current_user=user_from_actor(actor))


@router.post("/{id}/actions/{action}")
def action_automation_path(
    id: int,
    action: str,
    action_data: dict = None,
    db: Session = Depends(get_db),
    actor=Depends(require_agent_or_user),
):
    return run_automation_action(id, action, action_data or {}, db, current_user=user_from_actor(actor))


def run_automation_action(id: int, action: str, action_data: dict, db: Session, current_user: User | None = None):
    if action not in ["start", "stop", "pause", "resume", "archive", "run_now"]:
        raise HTTPException(400, "Invalid action")

    aut = db.query(Automation).filter(Automation.id == id, Automation.is_deleted == False).first()
    if not aut:
        raise HTTPException(404)

    if action == "archive":
        cancel_automation_tasks(db, aut.id, "Automation archived; pending/running tasks cancelled.")
        aut.status = "archived"
        aut.archived_at = datetime.utcnow()
    elif action == "start":
        return create_upload_task_for_automation(aut, action_data, db, action="start", current_user=current_user)
    elif action == "stop":
        cancelled = cancel_automation_tasks(db, aut.id, "Automation stopped by user.")
        aut.status = "stopped"
        db.commit()
        create_log(db, "warning", "Automation stopped by user.", "automation", aut.id, automation_id=aut.id, metadata={"cancelled_tasks": cancelled})
        return {"status": "stopped", "action": action, "cancelled_tasks": cancelled}
    elif action == "pause":
        aut.status = "paused"
    elif action == "resume":
        aut.status = "active"
    elif action == "run_now":
        return create_upload_task_for_automation(aut, action_data, db, action="run_now", current_user=current_user)
    db.commit()
    create_log(db, "info", f"Automation action {action}", "automation", aut.id, automation_id=aut.id)
    return {"status": "action executed", "action": action}


def create_upload_task_for_automation(
    aut: Automation,
    action_data: dict,
    db: Session,
    action: str = "run_now",
    current_user: User | None = None,
):
    active_tasks = active_automation_tasks(db, aut.id)
    if active_tasks:
        aut.status = "running"
        db.commit()
        create_log(
            db,
            "info",
            "Automation already has pending/running task.",
            "automation",
            aut.id,
            automation_id=aut.id,
            metadata={"task_ids": [task.id for task in active_tasks]},
        )
        return {"status": "already_running", "action": action, "task_ids": [task.id for task in active_tasks]}

    workspace = db.query(Workspace).filter(Workspace.id == aut.workspace_id, Workspace.is_deleted == False).first() if aut.workspace_id else None
    if not workspace:
        create_log(db, "error", "Automation workspace not found.", "automation", aut.id, automation_id=aut.id, metadata={"workspace_id": aut.workspace_id})
        raise HTTPException(400, "Automation workspace not found")
    normalized_folder_path = normalize_folder_path(aut.folder_path)
    if not normalized_folder_path:
        create_log(db, "warning", "Automation folder_path is empty.", "automation", aut.id, automation_id=aut.id, metadata={"folder_path": aut.folder_path})
        raise HTTPException(400, "Automation folder_path is required")

    config = automation_config(aut)
    session_user_id, session_source = resolve_session_user_id(
        db=db,
        aut=aut,
        workspace=workspace,
        config=config,
        current_user=current_user,
    )
    if current_user and safe_int(config.get("playground_user_id")) != current_user.id:
        config["playground_user_id"] = current_user.id
        save_automation_config(aut, config)

    action_data = action_data or {}
    payload_overrides = action_data.get("payload_overrides") or {}
    enabled_exts = sorted(enabled_extensions_from_config(config))
    payload = {
        "automation_id": aut.id,
        "automation_name": aut.name,
        "user_id": session_user_id,
        "workspace_id": workspace.id,
        "workspace_name": workspace.name,
        # URL direta do workspace no Playground (capturada na criacao ou cadastrada
        # manualmente). Quando presente, a automacao abre o workspace direto por ela,
        # sem precisar pesquisar pelo nome. Cai para a busca por nome se estiver vazia.
        "workspace_playground_url": workspace.playground_url or workspace.add_data_url or None,
        "folder_path": normalized_folder_path,
        "source_folder_path": normalized_folder_path,
        "files": [],
        "enabled_extensions": enabled_exts,
        "file_types": config.get("file_types") if isinstance(config.get("file_types"), list) else [],
        "batch_size": aut.batch_size or settings.UPLOAD_BATCH_SIZE,
        "batch_interval_seconds": aut.batch_interval_seconds or settings.DEFAULT_BATCH_INTERVAL_SECONDS,
        "monitoring_timeout_minutes": aut.monitoring_timeout_minutes or settings.DEFAULT_MONITORING_TIMEOUT_MINUTES,
        "monitor_interval_seconds": aut.monitor_interval_seconds or settings.DEFAULT_MONITOR_INTERVAL_SECONDS,
        "max_retries": aut.max_retries or 3,
        "temp_folder_path": aut.temp_folder_path,
        "full_execution": bool(aut.full_execution),
        "browser_channel": action_data.get("browser_channel") or "chromium",
        "headless": config.get("playwright_mode") == "headless",
        # "Executar apenas monitoramento de pasta": quando ligado, o agente apenas le a
        # pasta e copia os arquivos para a pasta temp, sem abrir a automacao web.
        "monitor_only": bool(config.get("monitor_only")),
    }
    payload.update(payload_overrides)
    payload["user_id"] = session_user_id
    task = AgentTask(
        task_type="upload_files_to_workspace",
        status="pending",
        payload_json=json.dumps(payload, ensure_ascii=False),
        created_by_id=session_user_id,
        max_attempts=aut.max_retries or 3,
    )
    db.add(task)
    aut.status = "running"
    db.commit()
    db.refresh(task)
    agent_status = latest_agent_status(db)
    create_log(
        db,
        "info",
        "Automation start requested; upload task created without synchronous folder scan.",
        "automation",
        aut.id,
        automation_id=aut.id,
        task_id=task.id,
        metadata={
            "folder_path": normalized_folder_path,
            "enabled_extensions": enabled_exts,
            "agent_status": agent_status,
            "session_user_id": session_user_id,
            "session_source": session_source,
            "full_execution": bool(aut.full_execution),
        },
    )
    create_log(db, "info", "Upload task pending; aguardando agente local.", "automation", aut.id, automation_id=aut.id, task_id=task.id)
    if agent_status.get("status") != "active":
        create_log(
            db,
            "warning",
            agent_status.get("message") or "Agente local nao esta ativo.",
            "automation",
            aut.id,
            automation_id=aut.id,
            task_id=task.id,
            metadata=agent_status,
        )
    return {
        "status": "task_created",
        "action": action,
        "task_id": task.id,
        "agent_status": agent_status,
        "agent_warning": agent_status.get("message") if agent_status.get("status") != "active" else None,
    }
