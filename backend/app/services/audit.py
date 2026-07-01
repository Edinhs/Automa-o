from sqlalchemy.orm import Session
from app.models.execution import ExecutionLog
import json


def create_log(
    db: Session,
    level: str,
    message: str,
    entity_type: str = None,
    entity_id: int = None,
    user_id: int = None,
    automation_id: int = None,
    file_id: int = None,
    task_id: int = None,
    metadata: dict | None = None,
    metadata_json: str | None = None,
):
    log = ExecutionLog(
        level=level,
        message=message,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        automation_id=automation_id,
        file_id=file_id,
        task_id=task_id,
        metadata_json=metadata_json or (json.dumps(metadata, ensure_ascii=False) if metadata else None),
    )
    db.add(log)
    db.commit()
    return log


def log_action(*args, **kwargs):
    return create_log(*args, **kwargs)
