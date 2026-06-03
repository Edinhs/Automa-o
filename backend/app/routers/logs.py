import csv
import io

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.execution import ExecutionLog
from app.services.audit import create_log
from fastapi.responses import PlainTextResponse
from app.core.timezone import sao_paulo_utc_iso

router = APIRouter()

# Cap defensivo para nao carregar a tabela inteira em memoria (risco de OOM).
MAX_EXPORT_ROWS = 50000


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


@router.get("")
def list_logs(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    logs = (
        db.query(ExecutionLog)
        .order_by(ExecutionLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [log_out(log) for log in logs]

@router.post("")
def post_log(data: dict, db: Session = Depends(get_db)):
    log = create_log(
        db,
        data.get("level", "info"),
        data.get("message", ""),
        data.get("entity_type"),
        data.get("entity_id"),
        user_id=data.get("user_id"),
        automation_id=data.get("automation_id"),
        file_id=data.get("file_id"),
        task_id=data.get("task_id"),
        metadata=data.get("metadata"),
        metadata_json=data.get("metadata_json"),
    )
    return log_out(log)

@router.get("/export")
def export_logs(
    db: Session = Depends(get_db),
    limit: int = Query(default=MAX_EXPORT_ROWS, ge=1, le=MAX_EXPORT_ROWS),
    offset: int = Query(default=0, ge=0),
):
    logs = (
        db.query(ExecutionLog)
        .order_by(ExecutionLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    create_log(db, "info", "Exported logs", "system")

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "level", "message", "created_at"])
    for log in logs:
        writer.writerow([log.id, log.level, log.message, sao_paulo_utc_iso(log.created_at)])
    return PlainTextResponse(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=logs.csv"},
    )
