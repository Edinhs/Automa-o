from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.serialization import parse_json_object
from app.core.timezone import parse_sao_paulo_to_utc_naive, sao_paulo_utc_iso
from app.db.session import get_db
from app.models.agent import AgentTask
from app.models.automation import Automation
from app.models.execution import ExecutionLog
from app.models.file import WorkspaceFile
from app.models.user import User
from app.models.workspace import Workspace

router = APIRouter()

STATUS_LABELS = {
    "pending": "Pendente",
    "running": "Em execução",
    "completed": "Finalizada com sucesso",
    "failed": "Finalizada com erro",
    "manual_review": "Ação manual",
    "cancelled": "Cancelada",
}

STATUS_FILTERS = {
    "pendente": "pending",
    "pending": "pending",
    "em execucao": "running",
    "running": "running",
    "finalizada com sucesso": "completed",
    "completed": "completed",
    "finalizada com erro": "failed",
    "failed": "failed",
    "acao manual": "manual_review",
    "manual_review": "manual_review",
    "parada manualmente": "cancelled",
    "cancelada": "cancelled",
    "cancelled": "cancelled",
}

SUCCESS_FILE_STATUSES = {"ready", "uploaded"}
ERROR_FILE_STATUSES = {"failed", "manual_review"}
ERROR_PLAYGROUND_STATUSES = {"error", "timeout", "notfound"}


def parse_datetime(value: str | None) -> datetime | None:
    try:
        return parse_sao_paulo_to_utc_naive(value)
    except ValueError:
        return None


def normalize_text(value: str | None) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(char for char in text if not unicodedata.combining(char))


def normalize_status_filter(value: str | None) -> str | None:
    key = normalize_text(value)
    if not key or key == "todos":
        return None
    return STATUS_FILTERS.get(key, value)


def task_payload(task: AgentTask) -> dict[str, Any]:
    return parse_json_object(task.payload_json)


def task_result(task: AgentTask) -> dict[str, Any]:
    return parse_json_object(task.result_json)


def task_automation_id(task: AgentTask, payload: dict[str, Any] | None = None) -> int | None:
    value = (payload or task_payload(task)).get("automation_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def task_workspace_id(task: AgentTask, payload: dict[str, Any] | None = None) -> int | None:
    value = (payload or task_payload(task)).get("workspace_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def task_user_id(task: AgentTask, payload: dict[str, Any] | None = None) -> int | None:
    payload = payload or task_payload(task)
    value = task.created_by_id or payload.get("user_id") or payload.get("requested_by")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def task_file_refs(task: AgentTask, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = payload or task_payload(task)
    refs: list[dict[str, Any]] = []
    for item in payload.get("files") or []:
        if isinstance(item, dict):
            refs.append(item)
    if payload.get("file_id") or payload.get("file_name"):
        refs.append(
            {
                "file_id": payload.get("file_id"),
                "file_name": payload.get("file_name"),
                "path": payload.get("temp_path") or payload.get("original_path"),
                "temp_path": payload.get("temp_path"),
                "original_path": payload.get("original_path"),
                "attempts": payload.get("attempts"),
            }
        )
    return refs


def unique_file_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for ref in refs:
        key = str(ref.get("file_id") or ref.get("id") or ref.get("file_name") or ref.get("name") or "")
        if not key:
            key = json.dumps(ref, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def task_file_ids(task: AgentTask, payload: dict[str, Any] | None = None) -> list[int]:
    ids: list[int] = []
    for ref in task_file_refs(task, payload):
        value = ref.get("file_id") or ref.get("id")
        try:
            if value is not None:
                file_id = int(value)
                if file_id not in ids:
                    ids.append(file_id)
        except (TypeError, ValueError):
            continue
    return ids


def file_to_dict(file: WorkspaceFile) -> dict[str, Any]:
    return {
        "id": file.id,
        "file_name": file.file_name,
        "original_path": file.original_path,
        "temp_path": file.temp_path,
        "pdf_path": file.pdf_path,
        "extension": file.extension,
        "size_bytes": file.size_bytes,
        "workspace_id": file.workspace_id,
        "automation_id": file.automation_id,
        "status": file.status,
        "local_status": file.status,
        "playground_status": file.playground_status,
        "workspace_status": file.playground_status,
        "attempts": file.attempts,
        "max_attempts": file.max_attempts,
        "converted_to_pdf": file.converted_to_pdf,
        "last_error": file.last_error,
        "error_message": file.last_error,
        "detected_at": sao_paulo_utc_iso(file.detected_at),
        "uploaded_at": sao_paulo_utc_iso(file.uploaded_at),
        "ready_at": sao_paulo_utc_iso(file.ready_at),
        "failed_at": sao_paulo_utc_iso(file.failed_at),
        "manual_review_at": sao_paulo_utc_iso(file.manual_review_at),
        "created_at": sao_paulo_utc_iso(file.created_at),
        "updated_at": sao_paulo_utc_iso(file.updated_at),
    }


def fallback_file_dict(ref: dict[str, Any], task: AgentTask, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ref.get("file_id") or ref.get("id") or ref.get("file_name") or ref.get("name"),
        "file_name": ref.get("file_name") or ref.get("name") or ref.get("path") or "-",
        "original_path": ref.get("original_path") or ref.get("path"),
        "temp_path": ref.get("temp_path") or ref.get("path"),
        "pdf_path": ref.get("pdf_path"),
        "workspace_id": task_workspace_id(task, payload),
        "automation_id": task_automation_id(task, payload),
        "status": ref.get("status") or "pending",
        "local_status": ref.get("status") or "pending",
        "playground_status": ref.get("playground_status") or "Pending",
        "workspace_status": ref.get("playground_status") or "Pending",
        "attempts": ref.get("attempts") or 0,
        "max_attempts": ref.get("max_attempts") or payload.get("max_attempts"),
        "converted_to_pdf": bool(ref.get("converted_to_pdf")),
        "last_error": ref.get("last_error") or ref.get("error_message"),
        "error_message": ref.get("error_message") or ref.get("last_error"),
        "created_at": sao_paulo_utc_iso(task.created_at),
        "updated_at": sao_paulo_utc_iso(task.updated_at),
    }


def files_for_task(db: Session, task: AgentTask, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = payload or task_payload(task)
    refs = unique_file_refs(task_file_refs(task, payload))
    ids = task_file_ids(task, payload)
    db_files_by_id: dict[int, WorkspaceFile] = {}
    if ids:
        db_files_by_id = {
            file.id: file
            for file in db.query(WorkspaceFile).filter(WorkspaceFile.id.in_(ids), WorkspaceFile.is_deleted == False).all()
        }

    rows: list[dict[str, Any]] = []
    emitted_ids: set[int] = set()
    for ref in refs:
        file_id = ref.get("file_id") or ref.get("id")
        try:
            numeric_id = int(file_id) if file_id is not None else None
        except (TypeError, ValueError):
            numeric_id = None
        if numeric_id is not None and numeric_id in db_files_by_id:
            rows.append(file_to_dict(db_files_by_id[numeric_id]))
            emitted_ids.add(numeric_id)
        else:
            rows.append(fallback_file_dict(ref, task, payload))

    for file_id, file in db_files_by_id.items():
        if file_id not in emitted_ids:
            rows.append(file_to_dict(file))
    return rows


def file_status_counts(files: list[dict[str, Any]]) -> dict[str, int]:
    total = len(files)
    success = 0
    errors = 0
    pending = 0
    for file in files:
        local_status = normalize_text(file.get("status") or file.get("local_status"))
        workspace_status = normalize_text(file.get("playground_status") or file.get("workspace_status"))
        if local_status in SUCCESS_FILE_STATUSES or workspace_status == "ready":
            success += 1
        elif local_status in ERROR_FILE_STATUSES or workspace_status in ERROR_PLAYGROUND_STATUSES:
            errors += 1
        else:
            pending += 1
    return {"total": total, "success": success, "errors": errors, "pending": pending}


def finished_at(task: AgentTask) -> datetime | None:
    return task.completed_at or task.failed_at


def duration_seconds(task: AgentTask) -> int | None:
    if not task.started_at:
        return None
    end = finished_at(task) or datetime.utcnow()
    return max(int((end - task.started_at).total_seconds()), 0)


def task_status_label(task: AgentTask) -> str:
    return STATUS_LABELS.get(task.status or "", task.status or "Pendente")


def log_to_dict(log: ExecutionLog) -> dict[str, Any]:
    log_type = str(log.level or "info").upper()
    return {
        "id": log.id,
        "level": log.level,
        "log_type": log_type,
        "type": log_type,
        "message": log.message,
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "automation_id": log.automation_id,
        "file_id": log.file_id,
        "task_id": log.task_id,
        "user_id": log.user_id,
        "metadata_json": log.metadata_json,
        "created_at": sao_paulo_utc_iso(log.created_at),
        "timestamp": sao_paulo_utc_iso(log.created_at),
    }


def entity_name(model: Any, db: Session, entity_id: int | None) -> str | None:
    if not entity_id:
        return None
    item = db.query(model).filter(model.id == entity_id).first()
    return getattr(item, "name", None) if item else None


def execution_out(db: Session, task: AgentTask) -> dict[str, Any]:
    payload = task_payload(task)
    files = files_for_task(db, task, payload)
    counts = file_status_counts(files)
    automation_id = task_automation_id(task, payload)
    workspace_id = task_workspace_id(task, payload)
    user_id = task_user_id(task, payload)
    result = task_result(task)
    summary = {
        "task_type": task.task_type,
        "raw_status": task.status,
        "attempts": task.attempts or 0,
        "max_attempts": task.max_attempts,
        "files_total": counts["total"],
        "files_success": counts["success"],
        "files_errors": counts["errors"],
        "files_pending": counts["pending"],
        "result_status": result.get("status"),
        "error_message": task.error_message,
    }
    return {
        "id": task.id,
        "run_code": f"TASK-{task.id:05d}",
        "task_type": task.task_type,
        "automation_id": automation_id,
        "automation_name": entity_name(Automation, db, automation_id),
        "workspace_id": workspace_id,
        "workspace_name": entity_name(Workspace, db, workspace_id) or payload.get("workspace_name"),
        "triggered_by_user_id": user_id,
        "triggered_by_user_name": entity_name(User, db, user_id),
        "started_at": sao_paulo_utc_iso(task.started_at),
        "created_at": sao_paulo_utc_iso(task.created_at),
        "finished_at": sao_paulo_utc_iso(finished_at(task)),
        "duration_seconds": duration_seconds(task),
        "total_files": counts["total"],
        "success_count": counts["success"],
        "error_count": counts["errors"],
        "status": task_status_label(task),
        "raw_status": task.status,
        "summary": summary,
    }


def get_started_task(db: Session, id: int) -> AgentTask:
    task = db.query(AgentTask).filter(
        AgentTask.id == id,
        AgentTask.is_deleted == False,
        AgentTask.started_at.isnot(None),
    ).first()
    if not task:
        raise HTTPException(404, "Execution not found")
    return task


@router.get("")
def list_executions(
    automation_id: Optional[int] = None,
    status: str = "",
    started_from: str = "",
    started_to: str = "",
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(AgentTask).filter(
        AgentTask.is_deleted == False,
        AgentTask.started_at.isnot(None),
    )
    status_filter = normalize_status_filter(status)
    if status_filter:
        query = query.filter(AgentTask.status == status_filter)
    start = parse_datetime(started_from)
    end = parse_datetime(started_to)
    if start:
        query = query.filter(AgentTask.started_at >= start)
    if end:
        query = query.filter(AgentTask.started_at <= end)

    safe_limit = min(max(int(limit or 100), 1), 1000)
    rows: list[dict[str, Any]] = []
    for task in query.order_by(AgentTask.started_at.desc(), AgentTask.id.desc()).all():
        payload = task_payload(task)
        if automation_id is not None and task_automation_id(task, payload) != automation_id:
            continue
        rows.append(execution_out(db, task))
        if len(rows) >= safe_limit:
            break
    return rows


@router.get("/{id}")
def execution_detail(id: int, db: Session = Depends(get_db)):
    return execution_out(db, get_started_task(db, id))


@router.get("/{id}/timeline")
def execution_timeline(id: int, db: Session = Depends(get_db)):
    task = get_started_task(db, id)
    items: list[dict[str, Any]] = []
    if task.started_at:
        items.append({"timestamp": sao_paulo_utc_iso(task.started_at), "kind": "TASK", "log_type": "INFO", "message": "Task started"})
    logs = (
        db.query(ExecutionLog)
        .filter(ExecutionLog.task_id == id)
        .order_by(ExecutionLog.created_at.asc(), ExecutionLog.id.asc())
        .all()
    )
    for log in logs:
        items.append(log_to_dict(log))
    end = finished_at(task)
    if end:
        items.append({"timestamp": sao_paulo_utc_iso(end), "kind": "TASK", "log_type": "INFO", "message": f"Task finished: {task_status_label(task)}"})
    return {"items": items}


@router.get("/{id}/files")
def execution_files(id: int, limit: int = 200, db: Session = Depends(get_db)):
    task = get_started_task(db, id)
    files = files_for_task(db, task)
    safe_limit = min(max(int(limit or 200), 1), 1000)
    return files[:safe_limit]


@router.get("/{id}/logs")
def execution_logs(id: int, limit: int = 300, db: Session = Depends(get_db)):
    get_started_task(db, id)
    safe_limit = min(max(int(limit or 300), 1), 1000)
    return [
        log_to_dict(log)
        for log in (
            db.query(ExecutionLog)
            .filter(ExecutionLog.task_id == id)
            .order_by(ExecutionLog.created_at.desc(), ExecutionLog.id.desc())
            .limit(safe_limit)
            .all()
        )
    ]


@router.get("/{id}/errors")
def execution_errors(id: int, db: Session = Depends(get_db)):
    task = get_started_task(db, id)
    files = [
        file
        for file in files_for_task(db, task)
        if normalize_text(file.get("status") or file.get("local_status")) in ERROR_FILE_STATUSES
        or normalize_text(file.get("playground_status") or file.get("workspace_status")) in ERROR_PLAYGROUND_STATUSES
        or file.get("last_error")
        or file.get("error_message")
    ]
    logs = [
        log_to_dict(log)
        for log in (
            db.query(ExecutionLog)
            .filter(
                ExecutionLog.task_id == id,
                ExecutionLog.level.in_(["error", "warning", "ERROR", "WARNING"]),
            )
            .order_by(ExecutionLog.created_at.desc(), ExecutionLog.id.desc())
            .all()
        )
    ]
    return {"files": files, "logs": logs}


@router.get("/{id}/summary")
def execution_summary(id: int, db: Session = Depends(get_db)):
    task = get_started_task(db, id)
    execution = execution_out(db, task)
    return {
        "execution_id": id,
        "files": execution["total_files"],
        "errors": execution["error_count"],
        "status": execution["status"],
        "summary": execution["summary"],
    }


@router.delete("/{id}")
def delete_execution(id: int, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id, AgentTask.is_deleted == False).first()
    if not task:
        raise HTTPException(404, detail="Execution not found")
    task.is_deleted = True
    task.deleted_at = datetime.utcnow()
    db.commit()
    from app.services.audit import create_log
    create_log(db, "warning", f"Execution marked as deleted: {task.id}", "agent_task", task.id, task_id=task.id)
    return {"status": "deleted"}


@router.post("/{id}/open-folder")
def open_execution_folder(id: int, db: Session = Depends(get_db)):
    task = db.query(AgentTask).filter(AgentTask.id == id, AgentTask.is_deleted == False).first()
    if not task:
        raise HTTPException(404, detail="Execução não encontrada")
    
    payload = task_payload(task)
    temp_folder_path = payload.get("temp_folder_path")
    if not temp_folder_path:
        copy_stats = payload.get("copy_stats") or {}
        temp_folder_path = copy_stats.get("staging_dir")
        if not temp_folder_path:
            files = task_file_refs(task, payload)
            if files:
                first_file = files[0]
                temp_path = first_file.get("temp_path") or first_file.get("path")
                if temp_path:
                    from pathlib import Path
                    temp_folder_path = str(Path(temp_path).parent)
    
    if not temp_folder_path:
        raise HTTPException(400, detail="Caminho temporário não encontrado nesta execução")
    
    from app.services.agent_tasks import enqueue_task
    enqueue_task(
        db=db,
        task_type="open_temp_folder",
        payload={"temp_folder_path": temp_folder_path},
        created_by_id=task.created_by_id
    )
    return {"message": "Ação solicitada. A pasta temporária será aberta no agente local."}

