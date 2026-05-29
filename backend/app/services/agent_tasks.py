from sqlalchemy.orm import Session
from app.models.agent import AgentTask
from app.services.audit import log_action
import json

def enqueue_task(
    db: Session,
    task_type: str,
    payload: dict,
    created_by_id: int = None
):
    task = AgentTask(
        task_type=task_type,
        payload_json=json.dumps(payload),
        created_by_id=created_by_id
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    
    log_action(
        db=db,
        level="INFO",
        message=f"AgentTask {task_type} created.",
        entity_type="AgentTask",
        entity_id=task.id,
        user_id=created_by_id
    )
    return task
