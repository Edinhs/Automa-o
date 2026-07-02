import csv
import io

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.execution import ExecutionLog
from app.services.audit import create_log
from fastapi.responses import StreamingResponse
from app.core.timezone import sao_paulo_utc_iso

router = APIRouter()


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
def list_logs(db: Session = Depends(get_db)):
    return [log_out(log) for log in db.query(ExecutionLog).order_by(ExecutionLog.created_at.desc()).limit(100).all()]

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
def export_logs(limit: int = 50000, db: Session = Depends(get_db)):
    # Limite + streaming: evita carregar toda a tabela em memoria de uma vez (antes: .all() sem
    # teto). O csv.writer tambem escapa virgulas/aspas/quebras de linha na mensagem (antes a
    # concatenacao crua quebrava o CSV / permitia injecao de coluna).
    safe_limit = min(max(int(limit or 50000), 1), 200000)
    create_log(db, "info", "Exported logs", "system")

    def iter_csv():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "level", "message", "created_at"])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        query = (
            db.query(ExecutionLog)
            .order_by(ExecutionLog.created_at.desc(), ExecutionLog.id.desc())
            .limit(safe_limit)
            .yield_per(1000)
        )
        for log in query:
            writer.writerow([log.id, log.level, log.message, sao_paulo_utc_iso(log.created_at)])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=logs.csv"},
    )
