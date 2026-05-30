import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import runtime_path, settings
from app.core.timezone import sao_paulo_utc_iso
from app.db.session import get_db
from app.models.agent import AgentTask
from app.models.execution import ExecutionLog
from app.models.file import WorkspaceFile
from app.models.user import User
from app.models.workspace import Workspace
from app.routers.deps import get_current_user
from app.services.audit import create_log

router = APIRouter()

FILE_FIELDS = {
    "file_name",
    "original_path",
    "temp_path",
    "pdf_path",
    "extension",
    "size_bytes",
    "content_sha256",
    "detection_source",
    "detection_task_id",
    "detection_classification",
    "workspace_id",
    "automation_id",
    "status",
    "playground_status",
    "attempts",
    "max_attempts",
    "converted_to_pdf",
    "last_error",
    "detected_at",
    "uploaded_at",
    "ready_at",
    "failed_at",
    "manual_review_at",
}

LOCAL_STATUS_ALIASES = {
    "detectado": "pending",
    "aguardando upload": "pending",
    "copiado para temporario": "pending",
    "copiado para temporário": "pending",
    "enviado": "uploaded",
    "reprocessando": "pending_retry",
    "acao manual": "manual_review",
    "ação manual": "manual_review",
    "finalizado": "ready",
    "falha definitiva": "failed",
}


def file_out(file: WorkspaceFile) -> dict:
    return {
        "id": file.id,
        "file_name": file.file_name,
        "original_path": file.original_path,
        "temp_path": file.temp_path,
        "pdf_path": file.pdf_path,
        "extension": file.extension,
        "size_bytes": file.size_bytes,
        "content_sha256": file.content_sha256,
        "detection_source": file.detection_source,
        "detection_task_id": file.detection_task_id,
        "detection_classification": file.detection_classification,
        "workspace_id": file.workspace_id,
        "automation_id": file.automation_id,
        "status": file.status,
        "playground_status": file.playground_status,
        "attempts": file.attempts,
        "max_attempts": file.max_attempts,
        "converted_to_pdf": file.converted_to_pdf,
        "last_error": file.last_error,
        "detected_at": sao_paulo_utc_iso(file.detected_at),
        "uploaded_at": sao_paulo_utc_iso(file.uploaded_at),
        "ready_at": sao_paulo_utc_iso(file.ready_at),
        "failed_at": sao_paulo_utc_iso(file.failed_at),
        "manual_review_at": sao_paulo_utc_iso(file.manual_review_at),
        "created_at": sao_paulo_utc_iso(file.created_at),
        "updated_at": sao_paulo_utc_iso(file.updated_at),
    }


def log_out(log: ExecutionLog) -> dict:
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


def clean_payload(data: dict) -> dict:
    clean = {key: value for key, value in (data or {}).items() if key in FILE_FIELDS}
    for key, value in list(clean.items()):
        if value == "":
            clean[key] = None
    return clean


def normalize_local_status(value: str | None) -> str | None:
    if not value:
        return None
    normalized = str(value).strip()
    if not normalized or normalized.lower() == "todos":
        return None
    return LOCAL_STATUS_ALIASES.get(normalized.lower(), normalized)


def safe_upload_filename(filename: str | None) -> str:
    raw_name = Path(str(filename or "")).name.strip().replace("\x00", "")
    if not raw_name:
        raw_name = "manual_upload"
    return "".join(char if char.isalnum() or char in " ._()-[]" else "_" for char in raw_name).strip() or "manual_upload"


def manual_upload_task_payload(
    *,
    workspace: Workspace,
    db_file: WorkspaceFile,
    current_user: User,
    saved_path: Path,
    headless: bool,
    monitoring_timeout_minutes: int | None,
    monitor_interval_seconds: int | None,
    note: str,
) -> dict:
    return {
        "manual_upload": True,
        "start_monitoring_after_upload": False,
        "note": note,
        "user_id": current_user.id,
        "workspace_id": workspace.id,
        "workspace_name": workspace.name,
        "files": [
            {
                "file_id": db_file.id,
                "file_name": db_file.file_name,
                "path": str(saved_path),
                "temp_path": str(saved_path),
                "original_path": db_file.original_path,
                "attempts": 0,
            }
        ],
        "batch_size": 1,
        "batch_interval_seconds": settings.DEFAULT_BATCH_INTERVAL_SECONDS,
        "monitoring_timeout_minutes": monitoring_timeout_minutes or settings.DEFAULT_MONITORING_TIMEOUT_MINUTES,
        "monitor_interval_seconds": monitor_interval_seconds or settings.DEFAULT_MONITOR_INTERVAL_SECONDS,
        "max_retries": 3,
        "temp_folder_path": str(runtime_path("TEMP_PATH")),
        "browser_channel": "chromium",
        "headless": bool(headless),
    }


@router.get("")
def list_files(
    workspace_id: Optional[int] = None,
    automation_id: Optional[int] = None,
    search: str = "",
    local_status: str = "",
    workspace_status: str = "",
    status: str = "",
    limit: int = 300,
    db: Session = Depends(get_db),
):
    query = db.query(WorkspaceFile).filter(WorkspaceFile.is_deleted == False)
    if workspace_id:
        query = query.filter(WorkspaceFile.workspace_id == workspace_id)
    if automation_id:
        query = query.filter(WorkspaceFile.automation_id == automation_id)
    local_status_value = normalize_local_status(local_status or status)
    if local_status_value:
        query = query.filter(WorkspaceFile.status == local_status_value)
    workspace_status_value = str(workspace_status or "").strip()
    if workspace_status_value and workspace_status_value.lower() != "todos":
        query = query.filter(WorkspaceFile.playground_status == workspace_status_value)
    search_value = str(search or "").strip()
    if search_value:
        pattern = f"%{search_value}%"
        query = query.filter(
            or_(
                WorkspaceFile.file_name.ilike(pattern),
                WorkspaceFile.original_path.ilike(pattern),
                WorkspaceFile.temp_path.ilike(pattern),
                WorkspaceFile.pdf_path.ilike(pattern),
            )
        )
    safe_limit = min(max(int(limit or 300), 1), 1000)
    return [file_out(file) for file in query.order_by(WorkspaceFile.updated_at.desc(), WorkspaceFile.created_at.desc()).limit(safe_limit).all()]


@router.post("")
def create_file(data: dict, db: Session = Depends(get_db)):
    clean = clean_payload(data)
    if not clean.get("file_name"):
        raise HTTPException(422, "file_name is required")
    if clean.get("detected_at") is None:
        clean["detected_at"] = datetime.utcnow()
    f = WorkspaceFile(**clean)
    db.add(f)
    db.commit()
    db.refresh(f)
    create_log(db, "info", f"File registered: {f.file_name}", "workspace_file", f.id, automation_id=f.automation_id, file_id=f.id)
    return file_out(f)


@router.post("/manual-upload")
def create_manual_upload(
    workspace_id: int = Form(...),
    file: UploadFile = File(...),
    note: str = Form(""),
    headless: bool = Form(False),
    monitoring_timeout_minutes: int | None = Form(None),
    monitor_interval_seconds: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.is_deleted == False).first()
    if not workspace:
        raise HTTPException(404, "Workspace not found")

    file_name = safe_upload_filename(file.filename)
    target_dir = runtime_path("TEMP_PATH") / "manual_uploads" / f"{datetime.utcnow():%Y%m%d%H%M%S%f}_{current_user.id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file_name
    try:
        with target_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        raise HTTPException(500, f"Unable to save manual upload: {exc}") from exc
    finally:
        file.file.close()

    size_bytes = target_path.stat().st_size if target_path.exists() else 0
    db_file = WorkspaceFile(
        file_name=file_name,
        original_path=file.filename or file_name,
        temp_path=str(target_path),
        extension=target_path.suffix.lower(),
        size_bytes=size_bytes,
        workspace_id=workspace.id,
        automation_id=None,
        status="pending",
        playground_status="Pending",
        detected_at=datetime.utcnow(),
        max_attempts=3,
    )
    db.add(db_file)
    db.flush()

    payload = manual_upload_task_payload(
        workspace=workspace,
        db_file=db_file,
        current_user=current_user,
        saved_path=target_path,
        headless=headless,
        monitoring_timeout_minutes=monitoring_timeout_minutes,
        monitor_interval_seconds=monitor_interval_seconds,
        note=note,
    )
    task = AgentTask(
        task_type="upload_files_to_workspace",
        status="pending",
        payload_json=json.dumps(payload, ensure_ascii=False),
        created_by_id=current_user.id,
        max_attempts=3,
    )
    db.add(task)
    db.commit()
    db.refresh(db_file)
    db.refresh(task)
    create_log(
        db,
        "info",
        "Manual upload task created.",
        "workspace_file",
        db_file.id,
        user_id=current_user.id,
        file_id=db_file.id,
        task_id=task.id,
        metadata={"workspace_id": workspace.id, "workspace_name": workspace.name, "file_name": file_name, "note": note},
    )
    return {"status": "task_created", "file_id": db_file.id, "task_id": task.id, "workspace_id": workspace.id}


@router.get("/upload-baseline/{automation_id}")
def get_upload_baseline(automation_id: int, db: Session = Depends(get_db)):
    # Inclui todos os registros que atingiram um estado terminal de sucesso:
    # - uploaded_at preenchido (upload confirmado pelo checkpoint do lote), OU
    # - status "ready" ou "uploaded" (fallback para registros legados sem uploaded_at).
    # Exclui status de erro/revisao manual para que arquivos com falha possam ser
    # reprocessados normalmente em ciclos futuros (comportamento aceito pelo usuario).
    files = (
        db.query(WorkspaceFile)
        .filter(
            WorkspaceFile.automation_id == automation_id,
            WorkspaceFile.is_deleted == False,
            WorkspaceFile.original_path.isnot(None),
            or_(
                WorkspaceFile.uploaded_at.isnot(None),
                WorkspaceFile.status.in_(["ready", "uploaded"]),
            ),
        )
        .order_by(WorkspaceFile.uploaded_at.desc(), WorkspaceFile.id.desc())
        .all()
    )
    return [
        {
            "id": file.id,
            "original_path": file.original_path,
            "content_sha256": file.content_sha256,
            "status": file.status,
            "uploaded_at": sao_paulo_utc_iso(file.uploaded_at),
            "ready_at": sao_paulo_utc_iso(file.ready_at),
        }
        for file in files
    ]


@router.get("/{id}")
def get_file(id: int, db: Session = Depends(get_db)):
    f = db.query(WorkspaceFile).filter(WorkspaceFile.id == id, WorkspaceFile.is_deleted == False).first()
    if not f:
        raise HTTPException(404)
    return file_out(f)


@router.put("/{id}")
def update_file(id: int, data: dict, db: Session = Depends(get_db)):
    f = db.query(WorkspaceFile).filter(WorkspaceFile.id == id, WorkspaceFile.is_deleted == False).first()
    if not f:
        raise HTTPException(404)
    for key, value in clean_payload(data).items():
        setattr(f, key, value)
    db.commit()
    db.refresh(f)
    create_log(db, "info", f"File updated: {f.file_name}", "workspace_file", f.id, automation_id=f.automation_id, file_id=f.id)
    return file_out(f)


@router.get("/{id}/logs")
def get_file_logs(id: int, db: Session = Depends(get_db)):
    return [log_out(log) for log in db.query(ExecutionLog).filter(ExecutionLog.file_id == id).order_by(ExecutionLog.created_at.desc()).all()]
