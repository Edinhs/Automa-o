from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.serialization import parse_json_object
from app.db.session import get_db
from app.models.agent import AgentTask, LocalAgent
from app.models.automation import Automation
from app.models.file import WorkspaceFile
from app.models.user import User
from app.models.workspace import Workspace
from app.routers.deps import get_or_create_local_user
from app.routers.reports import create_automatic_folder_monitoring_report
from app.services.audit import create_log

router = APIRouter()

OFFICIAL_TASK_TYPES = {
    "connect_playground_session",
    "create_playground_workspace",
    "add_playground_user_to_workspace",
    "upload_files_to_workspace",
    "monitor_workspace_files_status",
    "convert_and_retry_file",
    "open_temp_folder",
}

AUTOMATION_TASK_TYPES = {
    "upload_files_to_workspace",
    "monitor_workspace_files_status",
    "convert_and_retry_file",
}
ACTIVE_TASK_STATUSES = {"pending", "running"}


def current_user_from_authorization(db: Session, authorization: Optional[str]) -> Optional[User]:
    if settings.AUTH_DISABLED:
        return get_or_create_local_user(db)
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        return None
    subject = payload.get("sub")
    if subject is None:
        return None
    query = db.query(User).filter(User.is_deleted == False)
    if str(subject).isdigit():
        return query.filter(User.id == int(subject)).first()
    return query.filter((User.network_id == subject) | (User.email == subject)).first()


def encode_json(value: dict | list | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def safe_int(value) -> int | None:
    if value in [None, ""]:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_playground_data_languages(value) -> list[str]:
    languages = []
    for item in value or []:
        language = str(item).strip()
        if language and language not in languages:
            languages.append(language)
    return languages


def parse_payload(raw: str | None) -> dict:
    return parse_json_object(raw)


def task_payload(task: AgentTask) -> dict:
    return parse_payload(task.payload_json)


def task_automation_id(task: AgentTask) -> int | None:
    value = task_payload(task).get("automation_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def related_automation_tasks(db: Session, automation_id: int) -> list[AgentTask]:
    tasks = db.query(AgentTask).filter(
        AgentTask.is_deleted == False,
        AgentTask.task_type.in_(AUTOMATION_TASK_TYPES),
    ).all()
    return [task for task in tasks if task_automation_id(task) == automation_id]


def maybe_finalize_automation(db: Session, task: AgentTask) -> None:
    automation_id = task_automation_id(task)
    if not automation_id:
        return
    automation = db.query(Automation).filter(Automation.id == automation_id, Automation.is_deleted == False).first()
    if not automation or automation.status in {"stopped", "paused", "archived", "deleted"}:
        return
    related_tasks = related_automation_tasks(db, automation_id)
    if any(item.status in ACTIVE_TASK_STATUSES for item in related_tasks):
        return

    files = db.query(WorkspaceFile).filter(
        WorkspaceFile.automation_id == automation_id,
        WorkspaceFile.is_deleted == False,
    ).all()
    task_statuses = {item.status for item in related_tasks}
    file_statuses = {item.status for item in files}
    if "manual_review" in task_statuses or "manual_review" in file_statuses:
        automation.status = "manual_review"
        message = "Automation finished with files requiring manual review."
        level = "warning"
    elif "failed" in task_statuses or "failed" in file_statuses:
        automation.status = "failed"
        message = "Automation finished with failures."
        level = "error"
    elif files and file_statuses.issubset({"ready", "uploaded"}):
        automation.status = "completed"
        message = "Automation completed all files."
        level = "info"
    else:
        return
    db.commit()
    create_log(db, level, message, "automation", automation.id, automation_id=automation.id)


def update_user_playground_session(db: Session, task: AgentTask, data: dict) -> None:
    result = data.get("result") or data
    user_id = data.get("user_id") or result.get("user_id") or task.created_by_id
    user = db.query(User).filter(User.id == user_id, User.is_deleted == False).first() if user_id else None
    if not user:
        user = db.query(User).filter(User.is_deleted == False).order_by(User.id.asc()).first()
    if user:
        user.playground_connected = True
        user.playground_connected_at = datetime.utcnow()
        user.playground_session_path = (
            data.get("playground_session_path")
            or data.get("session_path")
            or result.get("playground_session_path")
            or result.get("session_path")
        )


def update_workspace_result(db: Session, task: AgentTask, data: dict) -> None:
    payload = parse_payload(task.payload_json)
    result = data.get("result") or data
    workspace_id = result.get("workspace_id") or payload.get("workspace_id")
    workspace_name = result.get("workspace_name") or payload.get("workspace_name") or payload.get("name")
    workspace = None
    if workspace_id:
        workspace = db.query(Workspace).filter(Workspace.id == int(workspace_id), Workspace.is_deleted == False).first()
    if not workspace and workspace_name:
        workspace = db.query(Workspace).filter(Workspace.name == workspace_name, Workspace.is_deleted == False).first()
    if not workspace and workspace_name:
        workspace = Workspace(name=workspace_name, owner_user_id=task.created_by_id)
        db.add(workspace)
        db.flush()
    if not workspace:
        return
    for key in ["playground_workspace_id", "playground_url", "add_data_url", "embedding_model", "created_via", "status"]:
        if key in result:
            setattr(workspace, key, result.get(key))
    if "data_languages" in result:
        workspace.data_languages = encode_json(result.get("data_languages"))
    workspace.updated_at = datetime.utcnow()


def update_files_from_result(db: Session, task: AgentTask, data: dict) -> None:
    payload = parse_payload(task.payload_json)
    result = data.get("result") or data
    status_map = result.get("statuses") or {}
    retry_names = set(result.get("retry") or [])
    manual_review_names = set(result.get("manual_review") or [])
    files = payload.get("files") or result.get("uploaded_files") or []
    now = datetime.utcnow()
    for item in files:
        if not isinstance(item, dict):
            continue
        file_id = item.get("file_id") or item.get("id")
        file_name = item.get("file_name") or item.get("name")
        db_file = db.query(WorkspaceFile).filter(WorkspaceFile.id == int(file_id)).first() if file_id else None
        if not db_file and file_name:
            db_file = db.query(WorkspaceFile).filter(WorkspaceFile.file_name == file_name, WorkspaceFile.is_deleted == False).first()
        if not db_file:
            continue
        file_status = item.get("status")
        playground_status = item.get("playground_status")
        if file_name in status_map:
            playground_status = status_map[file_name].get("status")
            if file_name in retry_names:
                file_status = "pending_retry"
            elif file_name in manual_review_names:
                file_status = "manual_review"
                db_file.manual_review_at = now
            elif playground_status == "Ready":
                file_status = "ready"
                db_file.ready_at = now
            elif playground_status in {"Error", "NotFound"}:
                file_status = "failed"
                db_file.failed_at = now
            elif playground_status == "Processing":
                file_status = "manual_review"
                db_file.manual_review_at = now
            elif playground_status == "Pending" and file_name in retry_names:
                file_status = "pending_retry"
        if file_status:
            db_file.status = file_status
        if playground_status:
            db_file.playground_status = playground_status
        if item.get("uploaded_path") or item.get("path"):
            db_file.uploaded_at = db_file.uploaded_at or now
        db_file.updated_at = now


def batch_uploaded_file(payload_files: list[Any], uploaded_item: dict[str, Any]) -> dict[str, Any] | None:
    uploaded_id = safe_int(uploaded_item.get("file_id") or uploaded_item.get("id"))
    uploaded_path = str(uploaded_item.get("path") or uploaded_item.get("temp_path") or uploaded_item.get("uploaded_path") or "")
    for item in payload_files:
        if not isinstance(item, dict):
            continue
        item_id = safe_int(item.get("file_id") or item.get("id"))
        if uploaded_id and item_id == uploaded_id:
            return item
        item_path = str(item.get("path") or item.get("temp_path") or "")
        if uploaded_path and item_path == uploaded_path:
            return item
    return None


@router.get("")
def list_agents(db: Session = Depends(get_db)):
    return db.query(LocalAgent).filter(LocalAgent.is_deleted == False).all()


@router.post("/heartbeat")
def heartbeat(data: dict, db: Session = Depends(get_db)):
    agent_name = data.get("name", "unknown")
    agent = db.query(LocalAgent).filter(LocalAgent.name == agent_name).first()
    if not agent:
        agent = LocalAgent(name=agent_name, machine_name=data.get("machine_name"), version=data.get("version"))
        db.add(agent)
    agent.status = "active"
    agent.machine_name = data.get("machine_name") or agent.machine_name
    agent.version = data.get("version") or agent.version
    agent.last_heartbeat_at = datetime.utcnow()
    db.commit()
    db.refresh(agent)
    return {"status": "ok", "agent_id": agent.id}


@router.post("/poll")
def poll_tasks(data: Optional[dict] = None, db: Session = Depends(get_db)):
    data = data or {}
    agent_id = data.get("agent_id")
    tasks = db.query(AgentTask).filter(
        AgentTask.status == "pending",
        AgentTask.is_deleted == False,
    ).order_by(
        (AgentTask.task_type != "connect_playground_session"),
        AgentTask.created_at.asc(),
    ).limit(5).all()
    for task in tasks:
        task.status = "running"
        task.started_at = task.started_at or datetime.utcnow()
        task.assigned_agent_id = agent_id or task.assigned_agent_id
        task.attempts = (task.attempts or 0) + 1
    db.commit()
    for task in tasks:
        db.refresh(task)
    return {"tasks": tasks}


@router.post("/tasks")
def create_task(data: dict, authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    task_type = data.get("task_type")
    if task_type not in OFFICIAL_TASK_TYPES:
        raise HTTPException(400, "Invalid task_type")
    current_user = current_user_from_authorization(db, authorization)
    payload = data.get("payload") or {}
    requested_user_id = safe_int(payload.get("user_id") or payload.get("requested_by") or data.get("created_by_id"))
    created_by_id = current_user.id if current_user else requested_user_id
    if task_type in OFFICIAL_TASK_TYPES and created_by_id and not payload.get("user_id"):
        payload["user_id"] = created_by_id
    if task_type == "create_playground_workspace":
        payload["data_languages"] = normalize_playground_data_languages(payload.get("data_languages"))
    task = AgentTask(
        task_type=task_type,
        status="pending",
        payload_json=encode_json(payload),
        created_by_id=created_by_id,
        max_attempts=data.get("max_attempts") or payload.get("max_attempts") or 3,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    create_log(
        db,
        "info",
        f"Agent task created: {task_type}",
        "agent_task",
        task.id,
        user_id=task.created_by_id,
        task_id=task.id,
        metadata={"task_type": task_type},
    )
    return {"task": task, "status": "task_created", "task_id": task.id}


@router.post("/tasks/{id}/start")
def start_task(id: int, data: Optional[dict] = None, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id).first()
    if not task:
        raise HTTPException(404)
    if task.status not in ["pending", "running"]:
        raise HTTPException(400, f"Task is not pending/running: {task.status}")
    if task.status == "pending":
        task.attempts = (task.attempts or 0) + 1
    task.status = "running"
    task.started_at = task.started_at or datetime.utcnow()
    task.assigned_agent_id = (data or {}).get("agent_id") or task.assigned_agent_id
    db.commit()
    create_log(db, "info", "Task running", "agent_task", task.id, user_id=task.created_by_id, task_id=task.id)
    return {"status": "running"}


@router.put("/tasks/{id}/payload")
def update_task_payload(id: int, data: dict, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id).first()
    if not task:
        raise HTTPException(404)
    if task.status not in ["pending", "running"]:
        raise HTTPException(400, f"Task payload cannot be updated while status is {task.status}")
    current_payload = task_payload(task)
    patch = data.get("payload_patch") or data.get("payload") or {}
    if not isinstance(patch, dict):
        raise HTTPException(422, "payload_patch must be an object")
    current_payload.update(patch)
    task.payload_json = encode_json(current_payload)
    db.commit()
    create_log(
        db,
        "info",
        "Task payload updated by local agent.",
        "agent_task",
        task.id,
        user_id=task.created_by_id,
        task_id=task.id,
        automation_id=task_automation_id(task),
        metadata={"updated_keys": sorted(patch.keys())},
    )
    return {"status": "updated", "task_id": task.id}


@router.post("/tasks/{id}/batch-complete")
def complete_upload_batch(id: int, data: dict, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id, AgentTask.is_deleted == False).first()
    if not task:
        raise HTTPException(404)
    if task.task_type != "upload_files_to_workspace":
        raise HTTPException(422, "Checkpoint de lote permitido apenas para task de upload.")
    if task.status != "running":
        raise HTTPException(400, f"Task de upload nao esta em execucao: {task.status}")

    batch_number = safe_int(data.get("batch_number"))
    uploaded_files = data.get("uploaded_files") or []
    if not batch_number or batch_number < 1:
        raise HTTPException(422, "batch_number invalido.")
    if not isinstance(uploaded_files, list) or not uploaded_files:
        raise HTTPException(422, "uploaded_files deve conter os arquivos confirmados do lote.")
    batch_folder_path = str(data.get("batch_folder_path") or "").strip() or None
    payload = task_payload(task)
    payload_files = payload.get("files") or []
    completed_batches = payload.get("completed_batches") if isinstance(payload.get("completed_batches"), list) else []
    existing_batch = next(
        (
            item for item in completed_batches
            if isinstance(item, dict)
            and safe_int(item.get("batch_number")) == batch_number
            and (str(item.get("batch_folder_path") or "").strip() or None) == batch_folder_path
        ),
        None,
    )
    if existing_batch:
        return {
            "status": "already_completed",
            "task_id": task.id,
            "batch_number": batch_number,
            "monitor_task_id": existing_batch.get("monitor_task_id"),
        }

    now = datetime.utcnow()
    canonical_files: list[dict[str, Any]] = []
    for incoming in uploaded_files:
        if not isinstance(incoming, dict):
            raise HTTPException(422, "Arquivo confirmado invalido no lote.")
        source_item = batch_uploaded_file(payload_files, incoming)
        if not source_item:
            raise HTTPException(422, "Arquivo confirmado nao pertence a task de upload.")
        source_batch = safe_int(source_item.get("batch_number"))
        source_folder = str(source_item.get("batch_folder_path") or "").strip() or None
        if source_batch and source_batch != batch_number:
            raise HTTPException(422, "Arquivo confirmado pertence a outro lote.")
        if source_folder and source_folder != batch_folder_path:
            raise HTTPException(422, "Arquivo confirmado pertence a outra subpasta de lote.")
        file_id = safe_int(source_item.get("file_id") or source_item.get("id"))
        db_file = db.query(WorkspaceFile).filter(WorkspaceFile.id == file_id, WorkspaceFile.is_deleted == False).first() if file_id else None
        if not db_file:
            raise HTTPException(422, "Arquivo confirmado nao encontrado no banco.")
        db_file.status = "uploaded"
        db_file.playground_status = "Pending"
        db_file.uploaded_at = db_file.uploaded_at or now
        db_file.updated_at = now
        canonical_files.append(
            {
                **source_item,
                "file_id": db_file.id,
                "file_name": db_file.file_name or source_item.get("file_name"),
                "uploaded_path": incoming.get("uploaded_path") or source_item.get("path") or source_item.get("temp_path"),
                "status": "uploaded",
                "playground_status": "Pending",
            }
        )

    monitor_task = None

    completed_entry = {
        "batch_number": batch_number,
        "batch_folder_path": batch_folder_path,
        "file_ids": [item.get("file_id") for item in canonical_files],
        "monitor_task_id": monitor_task.id if monitor_task else None,
        "completed_at": now.isoformat(),
    }
    payload["completed_batches"] = [*completed_batches, completed_entry]
    task.payload_json = encode_json(payload)
    db.commit()

    automation_id = task_automation_id(task)
    create_log(
        db,
        "info",
        f"Lote confirmado no backend: {batch_number}",
        "agent_task",
        task.id,
        user_id=task.created_by_id,
        task_id=task.id,
        automation_id=automation_id,
        metadata={
            "batch_number": batch_number,
            "batch_folder_path": batch_folder_path,
            "file_ids": completed_entry["file_ids"],
            "monitor_task_id": completed_entry["monitor_task_id"],
        },
    )
    return {
        "status": "completed",
        "task_id": task.id,
        "batch_number": batch_number,
        "monitor_task_id": completed_entry["monitor_task_id"],
    }


@router.post("/tasks/{id}/complete")
def complete_task(id: int, data: Optional[dict] = None, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id).first()
    if not task:
        raise HTTPException(404)
    if task.status == "cancelled":
        return {"status": "cancelled"}
    data = data or {}
    task.status = "completed"
    task.completed_at = datetime.utcnow()
    task.result_json = encode_json(data.get("result") or data)
    if task.task_type == "connect_playground_session":
        update_user_playground_session(db, task, data)
    elif task.task_type == "create_playground_workspace":
        update_workspace_result(db, task, data)
    elif task.task_type in {"upload_files_to_workspace", "monitor_workspace_files_status"}:
        update_files_from_result(db, task, data)
    db.commit()
    automation_id = task_automation_id(task)

    # === MONITORAMENTO ÚNICO APÓS O ENVIO DE TODOS OS ARQUIVOS ===
    if task.task_type == "upload_files_to_workspace":
        payload = parse_payload(task.payload_json)
        # "Executar apenas monitoramento de pasta": o agente copia os arquivos para a temp e
        # encerra sem abrir a automacao web. Nesse modo NUNCA enfileiramos o monitoramento web
        # (senao o Chromium subiria mesmo sem upload). Ver process_upload (monitor_only).
        if payload.get("monitor_only"):
            pass
        elif payload.get("start_monitoring_after_upload", True) is not False:
            # Pega todos os arquivos desta tarefa de upload registrados no banco
            files = db.query(WorkspaceFile).filter(
                WorkspaceFile.detection_task_id == task.id,
                WorkspaceFile.is_deleted == False,
            ).all()
            if files:
                canonical_files = []
                for f in files:
                    canonical_files.append({
                        "file_id": f.id,
                        "file_name": f.file_name,
                        "path": f.temp_path,
                        "temp_path": f.temp_path,
                        "original_path": f.original_path,
                        "status": f.status,
                        "playground_status": f.playground_status,
                    })
                monitor_payload = {
                    **payload,
                    "files": canonical_files,
                    "source_upload_task_id": task.id,
                }
                monitor_payload.pop("completed_batches", None)
                monitor_task = AgentTask(
                    task_type="monitor_workspace_files_status",
                    status="pending",
                    payload_json=encode_json(monitor_payload),
                    created_by_id=task.created_by_id,
                    max_attempts=task.max_attempts or payload.get("max_retries") or payload.get("max_attempts") or 3,
                )
                db.add(monitor_task)
                db.flush()
                db.commit()
                create_log(
                    db,
                    "info",
                    "Monitoramento unico enfileirado apos o envio de todos os arquivos.",
                    "agent_task",
                    monitor_task.id,
                    user_id=task.created_by_id,
                    task_id=monitor_task.id,
                    automation_id=automation_id,
                    metadata={"files": [item["file_name"] for item in canonical_files]},
                )

                # "Uploads concluidos = execucao concluida" (decisao do usuario): assim que TODOS
                # os lotes foram enviados, marca a automacao como concluida para o dashboard, mesmo
                # com o monitoramento web/conversao ainda em andamento. NAO e definitivo: o
                # monitor_task recem-criado fica 'pending' (ativo), entao maybe_finalize_automation
                # logo abaixo retorna cedo e NAO rebaixa este 'completed'. Quando o monitoramento
                # (e eventuais tasks de conversao/reenvio) terminarem, maybe_finalize_automation
                # reavalia e pode mover para manual_review/failed.
                automation = (
                    db.query(Automation)
                    .filter(Automation.id == automation_id, Automation.is_deleted == False)
                    .first()
                    if automation_id
                    else None
                )
                if automation and automation.status not in {"stopped", "paused", "archived", "deleted"}:
                    automation.status = "completed"
                    db.commit()
                    create_log(
                        db,
                        "info",
                        "Uploads concluidos: execucao marcada como concluida; monitoramento web/conversao seguem em segundo plano.",
                        "automation",
                        automation.id,
                        automation_id=automation_id,
                    )

    create_log(db, "info", "Task completed", "agent_task", task.id, user_id=task.created_by_id, task_id=task.id, automation_id=automation_id)
    maybe_finalize_automation(db, task)
    return {"status": "completed"}


@router.post("/tasks/{id}/fail")
def fail_task(id: int, data: dict, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id).first()
    if not task:
        raise HTTPException(404)
    if task.status == "cancelled":
        return {"status": "cancelled"}
    task.status = "failed"
    task.failed_at = datetime.utcnow()
    task.error_message = data.get("error_message")
    task.result_json = encode_json(data.get("result") or {})
    db.commit()
    automation_id = task_automation_id(task)
    create_log(
        db,
        "error",
        f"Task failed: {task.error_message}",
        "agent_task",
        task.id,
        user_id=task.created_by_id,
        task_id=task.id,
        automation_id=automation_id,
        metadata=data.get("metadata"),
    )
    maybe_finalize_automation(db, task)
    return {"status": "failed"}


@router.post("/tasks/{id}/manual-review")
def manual_review_task(id: int, data: Optional[dict] = None, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id).first()
    if not task:
        raise HTTPException(404)
    if task.status == "cancelled":
        return {"status": "cancelled"}
    data = data or {}
    task.status = "manual_review"
    task.failed_at = datetime.utcnow()
    task.error_message = data.get("error_message") or data.get("message")
    task.result_json = encode_json(data.get("result") or data)
    db.commit()
    automation_id = task_automation_id(task)
    create_log(
        db,
        "warning",
        f"Task manual_review: {task.error_message}",
        "agent_task",
        task.id,
        user_id=task.created_by_id,
        task_id=task.id,
        automation_id=automation_id,
        metadata=data.get("metadata"),
    )
    maybe_finalize_automation(db, task)
    return {"status": "manual_review"}


@router.post("/tasks/{id}/cancel")
def cancel_task(id: int, data: Optional[dict] = None, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id).first()
    if not task:
        raise HTTPException(404)
    data = data or {}
    if task.status not in {"completed", "failed", "manual_review", "cancelled"}:
        task.status = "cancelled"
        task.completed_at = task.completed_at or datetime.utcnow()
        task.error_message = data.get("message") or "Task cancelled."
        db.commit()
    automation_id = task_automation_id(task)
    create_log(
        db,
        "warning",
        data.get("message") or "Task cancelled.",
        "agent_task",
        task.id,
        user_id=task.created_by_id,
        task_id=task.id,
        automation_id=automation_id,
        metadata=data.get("metadata"),
    )
    maybe_finalize_automation(db, task)
    return {"status": "cancelled"}


@router.post("/tasks/{id}/log")
def log_task(id: int, data: dict, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id).first()
    if not task:
        raise HTTPException(404)
    level = data.get("level", "info")
    message = data.get("message", "")
    automation_id = data.get("automation_id") or task_automation_id(task)
    create_log(
        db,
        level,
        message,
        "agent_task",
        task.id,
        user_id=data.get("user_id") or task.created_by_id,
        task_id=task.id,
        automation_id=automation_id,
        file_id=data.get("file_id"),
        metadata=data.get("metadata"),
    )
    return {"status": "logged"}


@router.post("/tasks/{id}/folder-monitoring-report")
def automatic_folder_monitoring_report(id: int, db: Session = Depends(get_db)):
    return {
        "report": None,
        "saved": False,
        "created": False,
        "skipped": True,
        "environment_mode": "operational",
        "message": "Geração automática de relatórios foi desativada pelo administrador."
    }
