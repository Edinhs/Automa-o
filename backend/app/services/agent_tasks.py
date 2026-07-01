from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.agent import AgentTask
from app.models.automation import Automation
from app.models.file import WorkspaceFile
from app.services.audit import create_log, log_action

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUTOMATION_TASK_TYPES = {
    "upload_files_to_workspace",
    "monitor_workspace_files_status",
    "convert_and_retry_file",
}
_ACTIVE_TASK_STATUSES = {"pending", "running"}
_SUCCESS_FILE_STATUSES = {"ready", "uploaded", "resolved"}
_TERMINAL_AUTOMATION_STATUSES = {"stopped", "paused", "archived", "deleted"}


def _task_automation_id(task: AgentTask) -> int | None:
    if not task.payload_json:
        return None
    try:
        value = json.loads(task.payload_json)
        raw = value.get("automation_id") if isinstance(value, dict) else None
        return int(raw) if raw is not None else None
    except Exception:
        return None


def recalculate_automation_status(db: Session, automation_id: int | None) -> None:
    """Recalculate and persist automation status from current files and related tasks.

    Single source of truth for automation finalisation logic. Called from both
    the agent task lifecycle (agents.py) and dashboard file changes (files.py).

    Rules (priority order):
    1. Automation missing/deleted or in terminal status -> no-op.
    2. Any related task active (pending/running) -> no-op.
    3. 'manual_review' in any file/task -> automation = 'manual_review'.
    4. 'failed' in any file/task -> automation = 'failed'.
    5. Files exist and ALL file statuses in {ready, uploaded, resolved}
       -> automation = 'completed'.
    6. Current status is 'manual_review'/'failed' but no errors remain
       -> automation = 'active' (stale error cleared by user resolution).
    7. Otherwise -> no-op.

    Only commits and logs when the status actually changes.
    """
    if not automation_id:
        return

    automation = (
        db.query(Automation)
        .filter(Automation.id == automation_id, Automation.is_deleted == False)
        .first()
    )
    if not automation or automation.status in _TERMINAL_AUTOMATION_STATUSES:
        return

    related_tasks = [
        t
        for t in db.query(AgentTask)
        .filter(
            AgentTask.is_deleted == False,
            AgentTask.task_type.in_(_AUTOMATION_TASK_TYPES),
        )
        .all()
        if _task_automation_id(t) == automation_id
    ]

    if any(t.status in _ACTIVE_TASK_STATUSES for t in related_tasks):
        return

    files = (
        db.query(WorkspaceFile)
        .filter(
            WorkspaceFile.automation_id == automation_id,
            WorkspaceFile.is_deleted == False,
        )
        .all()
    )

    task_statuses = {t.status for t in related_tasks}
    file_statuses = {f.status for f in files}
    old_status = automation.status

    if "manual_review" in task_statuses or "manual_review" in file_statuses:
        new_status = "manual_review"
        message = "Automation finished with files requiring manual review."
        level = "warning"
    elif "failed" in task_statuses or "failed" in file_statuses:
        new_status = "failed"
        message = "Automation finished with failures."
        level = "error"
    elif files and file_statuses.issubset(_SUCCESS_FILE_STATUSES):
        new_status = "completed"
        message = "Automation completed all files."
        level = "info"
    elif old_status in {"manual_review", "failed"}:
        new_status = "active"
        message = "Automation status cleared after file resolution."
        level = "info"
    else:
        return

    if new_status == old_status:
        return

    automation.status = new_status
    db.commit()
    create_log(
        db,
        level,
        message,
        "automation",
        automation.id,
        automation_id=automation.id,
    )


# ---------------------------------------------------------------------------

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
