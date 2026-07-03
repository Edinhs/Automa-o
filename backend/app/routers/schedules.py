from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.timezone import now_sao_paulo_naive, sao_paulo_local_iso, sao_paulo_utc_iso, to_sao_paulo_naive
from app.db.session import get_db
from app.models.automation import Automation
from app.models.schedule import Schedule
from app.models.workspace import Workspace
from app.services.audit import create_log
from app.services.schedule_runner import (
    ACTIVE_STATUS,
    PAUSED_STATUS,
    build_schedule_name,
    compute_next_run,
    display_status,
    normalize_status,
    parse_local_datetime,
    run_due_schedule,
)

router = APIRouter()

VALID_FREQUENCIES = {"daily", "weekly", "monthly", "once", "interval"}

SCHEDULE_FIELDS = {
    "automation_id",
    "frequency_type",
    "time_of_day",
    "days_of_week",
    "day_of_month",
    "run_date",
    "start_date",
    "end_date",
    "interval_minutes",
    "status",
    "report_type",
    "report_format",
    "deliver_to_folder",
}


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "on", "yes", "sim"}


def schedule_payload(data: dict) -> dict:
    data = data or {}
    clean = {key: value for key, value in data.items() if key in SCHEDULE_FIELDS}
    frequency_type = str(clean.get("frequency_type") or data.get("frequency_type") or "").strip().lower()
    if frequency_type:
        clean["frequency_type"] = frequency_type
    if "starts_at" in data and "start_date" not in clean:
        clean["start_date"] = data.get("starts_at")
    if "expires_at" in data and "end_date" not in clean:
        clean["end_date"] = data.get("expires_at")

    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    if payload.get("hour") and "time_of_day" not in clean:
        clean["time_of_day"] = payload.get("hour")
    if "week_days" in payload and "days_of_week" not in clean:
        clean["days_of_week"] = json.dumps(payload.get("week_days"), ensure_ascii=False)
    if "month_day" in payload and "day_of_month" not in clean:
        clean["day_of_month"] = payload.get("month_day")

    if clean.get("frequency_type") == "once" and clean.get("start_date") and "run_date" not in clean:
        clean["run_date"] = clean["start_date"]

    for key in ["run_date", "start_date", "end_date"]:
        if key in clean:
            clean[key] = parse_local_datetime(clean[key])
    if clean.get("automation_id") in ["", "Todos", None]:
        clean["automation_id"] = None
    elif "automation_id" in clean:
        clean["automation_id"] = int(clean["automation_id"])
    if clean.get("day_of_month") in ["", None]:
        clean["day_of_month"] = None
    elif "day_of_month" in clean:
        clean["day_of_month"] = int(clean["day_of_month"])
    if clean.get("interval_minutes") in ["", None]:
        clean["interval_minutes"] = None
    elif "interval_minutes" in clean:
        clean["interval_minutes"] = max(int(clean["interval_minutes"]), 1)
    if "status" in clean:
        clean["status"] = normalize_status(clean.get("status"))
    if "deliver_to_folder" in clean:
        clean["deliver_to_folder"] = _as_bool(clean.get("deliver_to_folder"))
    return clean


def schedule_automation(db: Session, schedule: Schedule) -> Automation | None:
    if not schedule.automation_id:
        return None
    return db.query(Automation).filter(Automation.id == schedule.automation_id, Automation.is_deleted == False).first()


def validate_schedule(schedule: Schedule, db: Session, now: datetime | None = None) -> None:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    if schedule.frequency_type not in VALID_FREQUENCIES:
        raise HTTPException(422, "Invalid frequency_type")
    if not schedule.report_type:
        if not schedule.automation_id:
            raise HTTPException(422, "Automation is required")
        if not schedule_automation(db, schedule):
            raise HTTPException(404, "Automation not found")
    if schedule.frequency_type == "once":
        schedule.run_date = schedule.run_date or schedule.start_date
        schedule.start_date = schedule.start_date or schedule.run_date
        if not schedule.run_date:
            raise HTTPException(422, "Data e Hora is required")
        if schedule.run_date <= now:
            raise HTTPException(422, "Data e Hora must be in the future")
    if schedule.frequency_type == "interval" and not schedule.interval_minutes:
        schedule.interval_minutes = 60


def refresh_schedule(db: Session, schedule: Schedule) -> None:
    if schedule.report_type:
        freq_label = (
            "Diário" if schedule.frequency_type == "daily"
            else "Semanal" if schedule.frequency_type == "weekly"
            else "Mensal" if schedule.frequency_type == "monthly"
            else "Uma vez"
        )
        schedule.name = f"Relatório ({schedule.report_type}) - {freq_label}"
    else:
        automation = schedule_automation(db, schedule)
        schedule.name = build_schedule_name(schedule, automation)
    schedule.next_run_at = compute_next_run(schedule)
    if normalize_status(schedule.status) == ACTIVE_STATUS and schedule.next_run_at is None and schedule.end_date and schedule.end_date < now_sao_paulo_naive():
        schedule.status = "expired"


def schedule_out(schedule: Schedule, db: Session) -> dict:
    automation = schedule_automation(db, schedule)
    workspace = None
    if automation and automation.workspace_id:
        workspace = db.query(Workspace).filter(Workspace.id == automation.workspace_id, Workspace.is_deleted == False).first()
    return {
        "id": schedule.id,
        "automation_id": schedule.automation_id,
        "automation_name": automation.name if automation else None,
        "workspace_id": automation.workspace_id if automation else None,
        "workspace_name": workspace.name if workspace else "",
        "name": schedule.name,
        "frequency_label": schedule.name,
        "frequency_type": schedule.frequency_type,
        "time_of_day": schedule.time_of_day,
        "hour": schedule.time_of_day,
        "days_of_week": schedule.days_of_week,
        "day_of_month": schedule.day_of_month,
        "month_day": schedule.day_of_month,
        "run_date": sao_paulo_local_iso(schedule.run_date),
        "start_date": sao_paulo_local_iso(schedule.start_date),
        "starts_at": sao_paulo_local_iso(schedule.start_date),
        "end_date": sao_paulo_local_iso(schedule.end_date),
        "expires_at": sao_paulo_local_iso(schedule.end_date),
        "interval_minutes": schedule.interval_minutes,
        "next_run_at": sao_paulo_local_iso(schedule.next_run_at),
        "last_run_at": sao_paulo_local_iso(schedule.last_run_at),
        "last_task_id": schedule.last_task_id,
        "last_error": schedule.last_error,
        "status": display_status(schedule),
        "raw_status": schedule.status,
        "is_deleted": schedule.is_deleted,
        "deleted_at": sao_paulo_utc_iso(schedule.deleted_at),
        "created_at": sao_paulo_utc_iso(schedule.created_at),
        "updated_at": sao_paulo_utc_iso(schedule.updated_at),
        "report_type": schedule.report_type,
        "report_format": schedule.report_format,
        "deliver_to_folder": bool(schedule.deliver_to_folder),
    }


@router.get("")
def list_schedules(db: Session = Depends(get_db)):
    schedules = (
        db.query(Schedule)
        .filter(Schedule.is_deleted == False)
        .order_by(Schedule.next_run_at.is_(None), Schedule.next_run_at.asc(), Schedule.id.desc())
        .all()
    )
    return [schedule_out(schedule, db) for schedule in schedules]


@router.post("")
def create_schedule(data: dict, db: Session = Depends(get_db)):
    clean = schedule_payload(data)
    clean["status"] = clean.get("status") or ACTIVE_STATUS
    schedule = Schedule(**clean)
    validate_schedule(schedule, db)
    refresh_schedule(db, schedule)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    create_log(db, "info", f"Schedule created: {schedule.name}", "schedule", schedule.id, automation_id=schedule.automation_id)
    return schedule_out(schedule, db)


@router.get("/{id}")
def get_schedule(id: int, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == id, Schedule.is_deleted == False).first()
    if not schedule:
        raise HTTPException(404)
    return schedule_out(schedule, db)


@router.put("/{id}")
def update_schedule(id: int, data: dict, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == id, Schedule.is_deleted == False).first()
    if not schedule:
        raise HTTPException(404)
    for key, value in schedule_payload(data).items():
        setattr(schedule, key, value)
    schedule.last_error = None
    if schedule.status not in {PAUSED_STATUS, "completed"}:
        schedule.status = normalize_status(schedule.status)
    validate_schedule(schedule, db)
    refresh_schedule(db, schedule)
    db.commit()
    db.refresh(schedule)
    create_log(db, "info", f"Schedule updated: {schedule.name}", "schedule", schedule.id, automation_id=schedule.automation_id)
    return schedule_out(schedule, db)


@router.delete("/{id}")
def delete_schedule(id: int, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == id, Schedule.is_deleted == False).first()
    if not schedule:
        raise HTTPException(404)
    schedule.is_deleted = True
    schedule.deleted_at = datetime.utcnow()
    db.commit()
    create_log(db, "warning", "Schedule deleted", "schedule", schedule.id, automation_id=schedule.automation_id)
    return {"status": "deleted"}


@router.post("/{id}/pause")
def pause_schedule(id: int, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == id, Schedule.is_deleted == False).first()
    if not schedule:
        raise HTTPException(404)
    schedule.status = PAUSED_STATUS
    schedule.next_run_at = None
    db.commit()
    create_log(db, "info", "Schedule paused", "schedule", schedule.id, automation_id=schedule.automation_id)
    return schedule_out(schedule, db)


@router.post("/{id}/resume")
def resume_schedule(id: int, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == id, Schedule.is_deleted == False).first()
    if not schedule:
        raise HTTPException(404)
    schedule.status = ACTIVE_STATUS
    schedule.last_error = None
    validate_schedule(schedule, db)
    refresh_schedule(db, schedule)
    db.commit()
    create_log(db, "info", "Schedule resumed", "schedule", schedule.id, automation_id=schedule.automation_id)
    return schedule_out(schedule, db)


@router.post("/{id}/actions/{action}")
def schedule_action(id: int, action: str, db: Session = Depends(get_db)):
    if action == "pause":
        return pause_schedule(id, db)
    if action == "resume":
        return resume_schedule(id, db)
    if action == "delete":
        return delete_schedule(id, db)
    if action in {"run-now", "run_now"}:
        schedule = db.query(Schedule).filter(Schedule.id == id, Schedule.is_deleted == False).first()
        if not schedule:
            raise HTTPException(404)
        run_due_schedule(db, schedule)
        db.refresh(schedule)
        return schedule_out(schedule, db)
    raise HTTPException(400, "Invalid action")
