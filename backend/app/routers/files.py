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
    if clean.get("workspace_id") is None and clean.get("automation_id") is not None:
        from app.models.automation import Automation
        automation = db.query(Automation).filter(Automation.id == clean["automation_id"], Automation.is_deleted == False).first()
        if automation and automation.workspace_id is not None:
            clean["workspace_id"] = automation.workspace_id
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
    
    clean_data = clean_payload(data)
    # O agente, ao orquestrar o proprio reenvio EM LOTE (_build_resend_batch), marca cada arquivo
    # como pending_retry via este PUT. Sem o guard abaixo, cada marcacao dispararia um
    # convert_and_retry_file por arquivo (1-a-1) em PARALELO ao reenvio em lote -> PDF enviado
    # duas vezes. 'suppress_retry_task' (enviado pelo agente, nao e coluna) desliga o
    # auto-enfileiramento; o retry manual de 1 arquivo pelo dashboard NAO envia a flag e continua
    # gerando a task normalmente.
    suppress_retry_task = bool((data or {}).get("suppress_retry_task"))
    status_changed_to_retry = (
        clean_data.get("status") == "pending_retry"
        and f.status != "pending_retry"
        and not suppress_retry_task
    )

    for key, value in clean_data.items():
        setattr(f, key, value)
    
    if status_changed_to_retry:
        from app.models.automation import Automation
        workspace = db.query(Workspace).filter(Workspace.id == f.workspace_id, Workspace.is_deleted == False).first()
        automation = db.query(Automation).filter(Automation.id == f.automation_id, Automation.is_deleted == False).first() if f.automation_id else None
        
        config = {}
        if automation and automation.config_json:
            try:
                config = json.loads(automation.config_json)
            except:
                pass
        
        user_id = None
        if config and config.get("playground_user_id"):
            user_id = int(config["playground_user_id"])
        if not user_id and workspace and workspace.owner_user_id:
            user_id = int(workspace.owner_user_id)
        if not user_id:
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
                user_id = connected_user.id
        if not user_id:
            admin_user = (
                db.query(User)
                .filter(User.is_deleted == False, User.status == "active", User.role == "admin")
                .order_by(User.id.asc())
                .first()
            )
            if admin_user:
                user_id = admin_user.id
                
        payload = {
            "file_id": f.id,
            "automation_id": f.automation_id,
            "workspace_id": f.workspace_id,
            "workspace_name": workspace.name if workspace else "Workspace",
            "workspace_playground_url": (workspace.playground_url or workspace.add_data_url or None) if workspace else None,
            "temp_path": f.temp_path or f.original_path,
            "original_path": f.original_path,
            "attempts": f.attempts or 0,
            "max_attempts": f.max_attempts or 3,
            "temp_folder_path": automation.temp_folder_path if automation else str(runtime_path("TEMP_PATH")),
            "browser_channel": "chromium",
            "headless": config.get("playwright_mode") == "headless" if (config and "playwright_mode" in config) else False,
            "user_id": user_id,
        }
        
        task = AgentTask(
            task_type="convert_and_retry_file",
            status="pending",
            payload_json=json.dumps(payload, ensure_ascii=False),
            created_by_id=user_id,
            max_attempts=f.max_attempts or 3,
        )
        db.add(task)
        
    db.commit()
    db.refresh(f)
    create_log(db, "info", f"File updated: {f.file_name}", "workspace_file", f.id, automation_id=f.automation_id, file_id=f.id)
    if f.automation_id:
        from app.services.agent_tasks import recalculate_automation_status
        recalculate_automation_status(db, f.automation_id)
    return file_out(f)


@router.post("/{id}/resolve")
def resolve_file(id: int, db: Session = Depends(get_db)):
    f = db.query(WorkspaceFile).filter(WorkspaceFile.id == id, WorkspaceFile.is_deleted == False).first()
    if not f:
        raise HTTPException(404)
    f.status = "resolved"
    f.playground_status = "Resolved"
    if not f.ready_at:
        f.ready_at = datetime.utcnow()
    create_log(
        db,
        "info",
        f"File resolved: {f.file_name}",
        "workspace_file",
        f.id,
        automation_id=f.automation_id,
        file_id=f.id,
    )
    db.commit()
    db.refresh(f)
    if f.automation_id:
        from app.services.agent_tasks import recalculate_automation_status
        recalculate_automation_status(db, f.automation_id)
    return file_out(f)


def _resolve_retry_user_id(db: Session, config: dict, workspace: Optional[Workspace]) -> Optional[int]:
    """Resolve o user_id para a sessao Playground do reenvio (mesma logica do PUT)."""
    user_id = None
    if config and config.get("playground_user_id"):
        user_id = int(config["playground_user_id"])
    if not user_id and workspace and workspace.owner_user_id:
        user_id = int(workspace.owner_user_id)
    if not user_id:
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
            user_id = connected_user.id
    if not user_id:
        admin_user = (
            db.query(User)
            .filter(User.is_deleted == False, User.status == "active", User.role == "admin")
            .order_by(User.id.asc())
            .first()
        )
        if admin_user:
            user_id = admin_user.id
    return user_id


@router.post("/reprocess")
def reprocess_files(data: dict, db: Session = Depends(get_db)):
    """Reprocessa em LOTE os arquivos Error/Processing/pending_retry: converte na pasta PDF
    (fora do temp) e enfileira UMA unica task de reenvio por automacao (envia tudo de uma vez).

    Cria a task de reenvio diretamente (sem passar pelo auto-enfileiramento por arquivo do
    PUT /files/{id}), evitando tasks duplicadas.
    """
    from app.models.automation import Automation

    file_ids = [int(x) for x in (data.get("file_ids") or []) if x is not None]
    automation_id = data.get("automation_id")

    query = db.query(WorkspaceFile).filter(WorkspaceFile.is_deleted == False)
    if file_ids:
        query = query.filter(WorkspaceFile.id.in_(file_ids))
    elif automation_id:
        query = query.filter(
            WorkspaceFile.automation_id == int(automation_id),
            or_(
                WorkspaceFile.status.in_(["failed", "manual_review", "pending_retry"]),
                WorkspaceFile.playground_status.in_(["Error", "error", "Processing", "processing"]),
            ),
        )
    else:
        raise HTTPException(400, detail="Informe file_ids ou automation_id.")

    files = query.all()
    if not files:
        raise HTTPException(400, detail="Nenhum arquivo para reprocessar.")

    # Agrupa por automacao: cada automacao gera UMA task de reenvio em lote.
    groups: dict[int, list[WorkspaceFile]] = {}
    for f in files:
        groups.setdefault(int(f.automation_id or 0), []).append(f)

    created_tasks: list[int] = []
    for aut_id, group in groups.items():
        automation = (
            db.query(Automation).filter(Automation.id == aut_id, Automation.is_deleted == False).first()
            if aut_id else None
        )
        workspace_id = group[0].workspace_id
        workspace = (
            db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.is_deleted == False).first()
            if workspace_id else None
        )
        config = {}
        if automation and automation.config_json:
            try:
                config = json.loads(automation.config_json)
            except Exception:
                config = {}
        user_id = _resolve_retry_user_id(db, config, workspace)

        files_payload = []
        for f in group:
            f.status = "pending_retry"
            files_payload.append(
                {
                    "file_id": f.id,
                    "file_name": f.file_name,
                    "original_path": f.original_path,
                    "temp_path": f.temp_path or f.original_path,
                    "attempts": f.attempts or 0,
                }
            )

        payload = {
            "automation_id": aut_id or None,
            "workspace_id": workspace_id,
            "workspace_name": workspace.name if workspace else "Workspace",
            "workspace_playground_url": (workspace.playground_url or workspace.add_data_url or None) if workspace else None,
            "folder_path": automation.folder_path if automation else None,
            "temp_folder_path": automation.temp_folder_path if automation else str(runtime_path("TEMP_PATH")),
            "browser_channel": "chromium",
            "headless": config.get("playwright_mode") == "headless" if (config and "playwright_mode" in config) else False,
            "user_id": user_id,
            "max_attempts": (automation.max_retries if (automation and automation.max_retries) else 3),
            "files": files_payload,
        }
        task = AgentTask(
            task_type="convert_and_retry_file",
            status="pending",
            payload_json=json.dumps(payload, ensure_ascii=False),
            created_by_id=user_id,
            max_attempts=payload["max_attempts"],
        )
        db.add(task)
        db.flush()
        created_tasks.append(task.id)
        create_log(
            db, "info", f"Reprocesso em lote enfileirado ({len(group)} arquivo(s))",
            "automation", aut_id or None, automation_id=aut_id or None,
        )

    db.commit()
    return {"status": "queued", "tasks": created_tasks, "files": len(files)}


@router.delete("/{id}")
def delete_file(id: int, db: Session = Depends(get_db)):
    f = db.query(WorkspaceFile).filter(WorkspaceFile.id == id, WorkspaceFile.is_deleted == False).first()
    if not f:
        raise HTTPException(404, detail="File not found")
    f.is_deleted = True
    f.deleted_at = datetime.utcnow()
    db.commit()
    create_log(db, "warning", f"File marked as deleted: {f.file_name}", "workspace_file", f.id, automation_id=f.automation_id, file_id=f.id)
    return {"status": "deleted"}


@router.get("/{id}/logs")
def get_file_logs(id: int, db: Session = Depends(get_db)):
    return [log_out(log) for log in db.query(ExecutionLog).filter(ExecutionLog.file_id == id).order_by(ExecutionLog.created_at.desc()).all()]
