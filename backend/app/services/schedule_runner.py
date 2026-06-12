from __future__ import annotations

import asyncio
import calendar
import contextlib
import json
from datetime import datetime, time, timedelta
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import SUPPORTED_ENVIRONMENTS, environment_scope, settings
from app.core.timezone import now_sao_paulo_naive, parse_sao_paulo_datetime, to_sao_paulo_naive
from app.db.session import SessionLocal, session_for_environment
from app.models.automation import Automation
from app.models.report_delivery import ReportDelivery
from app.models.schedule import Schedule
from app.routers.automations import create_upload_task_for_automation
from app.services.audit import create_log

ACTIVE_STATUS = "active"
PAUSED_STATUS = "paused"
COMPLETED_STATUS = "completed"
ERROR_STATUS = "error"
EXPIRED_STATUS = "expired"

STATUS_ALIASES = {
    "ativo": ACTIVE_STATUS,
    "active": ACTIVE_STATUS,
    "aguardando próxima execução": ACTIVE_STATUS,
    "aguardando proxima execucao": ACTIVE_STATUS,
    "pausado": PAUSED_STATUS,
    "paused": PAUSED_STATUS,
    "concluido": COMPLETED_STATUS,
    "concluído": COMPLETED_STATUS,
    "completed": COMPLETED_STATUS,
    "com erro": ERROR_STATUS,
    "erro": ERROR_STATUS,
    "error": ERROR_STATUS,
    "expirado": EXPIRED_STATUS,
    "expired": EXPIRED_STATUS,
}
ACTIVE_STATUS_VALUES = tuple({ACTIVE_STATUS, *[key for key, value in STATUS_ALIASES.items() if value == ACTIVE_STATUS]})

WEEKDAY_ALIASES = {
    "seg": 0,
    "segunda": 0,
    "mon": 0,
    "monday": 0,
    "ter": 1,
    "terça": 1,
    "terca": 1,
    "tue": 1,
    "tuesday": 1,
    "qua": 2,
    "quarta": 2,
    "wed": 2,
    "wednesday": 2,
    "qui": 3,
    "quinta": 3,
    "thu": 3,
    "thursday": 3,
    "sex": 4,
    "sexta": 4,
    "fri": 4,
    "friday": 4,
    "sáb": 5,
    "sab": 5,
    "sábado": 5,
    "sabado": 5,
    "sat": 5,
    "saturday": 5,
    "dom": 6,
    "domingo": 6,
    "sun": 6,
    "sunday": 6,
}

_runner_task: asyncio.Task | None = None


def normalize_status(value: str | None) -> str:
    raw = str(value or ACTIVE_STATUS).strip().lower()
    return STATUS_ALIASES.get(raw, raw or ACTIVE_STATUS)


def display_status(schedule: Schedule, now: datetime | None = None) -> str:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    status = normalize_status(schedule.status)
    if status == ACTIVE_STATUS and schedule.end_date and schedule.end_date < now and not schedule.next_run_at:
        return "Expirado"
    return {
        ACTIVE_STATUS: "Ativo",
        PAUSED_STATUS: "Pausado",
        COMPLETED_STATUS: "Concluído",
        ERROR_STATUS: "Com erro",
        EXPIRED_STATUS: "Expirado",
    }.get(status, schedule.status or "Ativo")


def parse_local_datetime(value):
    return parse_sao_paulo_datetime(value)


def parse_time_of_day(value: str | None) -> time:
    raw = str(value or "08:00").strip()
    try:
        hour, minute = raw.split(":", 1)
        return time(hour=int(hour), minute=int(minute[:2]))
    except Exception:
        return time(hour=8, minute=0)


def parse_weekdays(raw: str | None, fallback: int) -> list[int]:
    if not raw:
        return [fallback]
    try:
        values = json.loads(raw)
    except Exception:
        values = [raw]
    if not isinstance(values, list):
        values = [values]
    days: list[int] = []
    for value in values:
        key = str(value).strip().lower()
        day = WEEKDAY_ALIASES.get(key)
        if day is not None and day not in days:
            days.append(day)
    return days or [fallback]


def _combine(date_value: datetime, run_time: time) -> datetime:
    return datetime.combine(date_value.date(), run_time)


def _within_end(schedule: Schedule, candidate: datetime | None) -> datetime | None:
    if not candidate:
        return None
    if schedule.end_date and candidate > schedule.end_date:
        return None
    return candidate


def _next_daily(schedule: Schedule, now: datetime) -> datetime | None:
    run_time = parse_time_of_day(schedule.time_of_day)
    window_start = max(schedule.start_date or now, now)
    candidate = datetime.combine(window_start.date(), run_time)
    if candidate < window_start:
        candidate += timedelta(days=1)
    return _within_end(schedule, candidate)


def _next_interval(schedule: Schedule, now: datetime) -> datetime | None:
    interval = max(int(schedule.interval_minutes or 60), 1)
    candidate = schedule.start_date or now
    if candidate <= now:
        elapsed_seconds = max((now - candidate).total_seconds(), 0)
        steps = int(elapsed_seconds // (interval * 60)) + 1
        candidate += timedelta(minutes=interval * steps)
    return _within_end(schedule, candidate)


def _next_weekly(schedule: Schedule, now: datetime) -> datetime | None:
    run_time = parse_time_of_day(schedule.time_of_day)
    window_start = max(schedule.start_date or now, now)
    days = parse_weekdays(schedule.days_of_week, window_start.weekday())
    for offset in range(0, 15):
        day = window_start + timedelta(days=offset)
        if day.weekday() not in days:
            continue
        candidate = datetime.combine(day.date(), run_time)
        if candidate >= window_start:
            return _within_end(schedule, candidate)
    return None


def _next_monthly(schedule: Schedule, now: datetime) -> datetime | None:
    run_time = parse_time_of_day(schedule.time_of_day)
    window_start = max(schedule.start_date or now, now)
    requested_day = max(int(schedule.day_of_month or 1), 1)
    year = window_start.year
    month = window_start.month
    for _ in range(0, 18):
        last_day = calendar.monthrange(year, month)[1]
        day = min(requested_day, last_day)
        candidate = datetime.combine(datetime(year, month, day).date(), run_time)
        if candidate >= window_start:
            return _within_end(schedule, candidate)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return None


def compute_next_run(schedule: Schedule, now: datetime | None = None) -> datetime | None:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    frequency = str(schedule.frequency_type or "").strip().lower()
    if normalize_status(schedule.status) != ACTIVE_STATUS:
        return None
    if frequency == "once":
        if schedule.last_run_at:
            return None
        candidate = schedule.run_date or schedule.start_date
        return _within_end(schedule, candidate) if candidate and candidate >= now else None
    if frequency == "interval":
        return _next_interval(schedule, now)
    if frequency == "daily":
        return _next_daily(schedule, now)
    if frequency == "weekly":
        return _next_weekly(schedule, now)
    if frequency == "monthly":
        return _next_monthly(schedule, now)
    return None


def build_schedule_name(schedule: Schedule, automation: Automation | None = None) -> str:
    automation_name = automation.name if automation else f"Automação {schedule.automation_id or ''}".strip()
    frequency = str(schedule.frequency_type or "").lower()
    if frequency == "once":
        when = schedule.run_date or schedule.start_date
        when_label = when.strftime("%d/%m/%Y %H:%M") if when else "sem data"
        return f"{automation_name} - Uma vez em {when_label}"
    if frequency == "interval":
        return f"{automation_name} - A cada {schedule.interval_minutes or 60} min"
    if frequency == "daily":
        return f"{automation_name} - Diário às {schedule.time_of_day or '08:00'}"
    if frequency == "weekly":
        return f"{automation_name} - Semanal às {schedule.time_of_day or '08:00'}"
    if frequency == "monthly":
        return f"{automation_name} - Mensal dia {schedule.day_of_month or 1} às {schedule.time_of_day or '08:00'}"
    return f"{automation_name} - Agendamento"


def due_schedules(db: Session, now: datetime | None = None) -> Iterable[Schedule]:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    return (
        db.query(Schedule)
        .filter(
            Schedule.is_deleted == False,
            or_(Schedule.status.is_(None), Schedule.status.in_(ACTIVE_STATUS_VALUES)),
            Schedule.next_run_at.isnot(None),
            Schedule.next_run_at <= now,
        )
        .order_by(Schedule.next_run_at.asc(), Schedule.id.asc())
        .all()
    )


def hydrate_missing_next_runs(db: Session, now: datetime | None = None) -> None:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    changed = False
    schedules = (
        db.query(Schedule)
        .filter(Schedule.is_deleted == False, or_(Schedule.status.is_(None), Schedule.status.in_(ACTIVE_STATUS_VALUES)))
        .all()
    )
    for schedule in schedules:
        status = normalize_status(schedule.status)
        if schedule.status != status:
            schedule.status = status
            changed = True
        if status != ACTIVE_STATUS:
            continue
        next_run = compute_next_run(schedule, now)
        if schedule.next_run_at != next_run and not (schedule.next_run_at and schedule.next_run_at <= now):
            schedule.next_run_at = next_run
            schedule.last_error = None
            changed = True
    if changed:
        db.commit()


def mark_schedule_error(db: Session, schedule: Schedule, message: str) -> None:
    schedule.status = ERROR_STATUS
    schedule.last_error = message
    schedule.next_run_at = None
    schedule.updated_at = datetime.utcnow()
    db.commit()
    create_log(db, "error", message, "schedule", schedule.id, automation_id=schedule.automation_id)


def run_due_schedule(db: Session, schedule: Schedule, now: datetime | None = None) -> None:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    automation = db.query(Automation).filter(
        Automation.id == schedule.automation_id,
        Automation.is_deleted == False,
    ).first()
    if not automation:
        mark_schedule_error(db, schedule, "Schedule automation not found.")
        return
    try:
        result = create_upload_task_for_automation(
            automation,
            {"trigger": "schedule", "payload_overrides": {"schedule_id": schedule.id}},
            db,
            action="schedule",
        )
        if result.get("status") == "no_files":
            mark_schedule_error(db, schedule, "Schedule found no files to process.")
            return
        task_id = result.get("task_id")
        if not task_id and result.get("task_ids"):
            task_id = result["task_ids"][0]
        schedule.last_run_at = now
        schedule.last_task_id = task_id
        schedule.last_error = None
        if str(schedule.frequency_type or "").lower() == "once":
            schedule.status = COMPLETED_STATUS
            schedule.next_run_at = None
        else:
            schedule.next_run_at = compute_next_run(schedule, now + timedelta(seconds=1))
            if schedule.next_run_at is None:
                schedule.status = EXPIRED_STATUS
        schedule.updated_at = datetime.utcnow()
        db.commit()
        create_log(
            db,
            "info",
            f"Schedule triggered automation: {automation.name}",
            "schedule",
            schedule.id,
            automation_id=automation.id,
            task_id=task_id,
            metadata={"schedule_id": schedule.id, "result": result},
        )
    except HTTPException as exc:
        mark_schedule_error(db, schedule, str(exc.detail))
    except Exception as exc:
        mark_schedule_error(db, schedule, str(exc) or exc.__class__.__name__)


def run_due_schedules_once(now: datetime | None = None, db: Session | None = None) -> int:
    own_session = db is None
    db = db or SessionLocal()
    triggered = 0
    try:
        hydrate_missing_next_runs(db, now)
        for schedule in due_schedules(db, now):
            run_due_schedule(db, schedule, now)
            triggered += 1
        return triggered
    finally:
        if own_session:
            db.close()


def run_due_schedules_for_all_environments(now: datetime | None = None) -> int:
    triggered = 0
    for environment in SUPPORTED_ENVIRONMENTS:
        with environment_scope(environment):
            db = session_for_environment(environment)
            try:
                triggered += run_due_schedules_once(now, db)
            finally:
                db.close()
    return triggered


# ===================== Envio agendado de relatorios ao Teams =====================
# Reusa compute_next_run / normalize_status (ReportDelivery tem os mesmos campos de
# agendamento do Schedule), entao toda a logica de frequencia e compartilhada.


def report_delivery_filters(delivery: ReportDelivery) -> dict:
    """Filtros (formato esperado por reports.build_sections) para o periodo da entrega."""
    end = datetime.utcnow()
    start = None
    if delivery.period_days:
        try:
            start = end - timedelta(days=int(delivery.period_days))
        except (TypeError, ValueError):
            start = None
    return {
        "start": start,
        "end": end,
        "automation_id": delivery.automation_id,
        "workspace_id": delivery.workspace_id,
        "status": None,
        "source_task_id": None,
    }


def due_report_deliveries(db: Session, now: datetime | None = None) -> Iterable[ReportDelivery]:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    return (
        db.query(ReportDelivery)
        .filter(
            ReportDelivery.is_deleted == False,
            or_(ReportDelivery.status.is_(None), ReportDelivery.status.in_(ACTIVE_STATUS_VALUES)),
            ReportDelivery.next_run_at.isnot(None),
            ReportDelivery.next_run_at <= now,
        )
        .order_by(ReportDelivery.next_run_at.asc(), ReportDelivery.id.asc())
        .all()
    )


def hydrate_missing_report_delivery_next_runs(db: Session, now: datetime | None = None) -> None:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    changed = False
    deliveries = (
        db.query(ReportDelivery)
        .filter(ReportDelivery.is_deleted == False, or_(ReportDelivery.status.is_(None), ReportDelivery.status.in_(ACTIVE_STATUS_VALUES)))
        .all()
    )
    for delivery in deliveries:
        status = normalize_status(delivery.status)
        if delivery.status != status:
            delivery.status = status
            changed = True
        if status != ACTIVE_STATUS:
            continue
        next_run = compute_next_run(delivery, now)
        if delivery.next_run_at != next_run and not (delivery.next_run_at and delivery.next_run_at <= now):
            delivery.next_run_at = next_run
            delivery.last_error = None
            changed = True
    if changed:
        db.commit()


def run_due_report_delivery(db: Session, delivery: ReportDelivery, now: datetime | None = None) -> None:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    is_once = str(delivery.frequency_type or "").lower() == "once"
    try:
        from app.services.integrations.report_teams import send_report_to_teams  # import tardio

        sent = send_report_to_teams(
            db,
            report_type=delivery.report_type or "Relatório Geral",
            filters=report_delivery_filters(delivery),
            message=delivery.message or "",
            target=delivery.target,
            created_by_id=delivery.created_by_id,
        )
        delivery.last_run_at = now
        delivery.last_delivery_id = sent.id
        delivery.last_error = None
        if is_once:
            delivery.status = COMPLETED_STATUS
            delivery.next_run_at = None
        else:
            delivery.next_run_at = compute_next_run(delivery, now + timedelta(seconds=1))
            if delivery.next_run_at is None:
                delivery.status = EXPIRED_STATUS
        delivery.updated_at = datetime.utcnow()
        db.commit()
        create_log(
            db,
            "info",
            f"Report delivery to Teams triggered: {delivery.name or delivery.report_type}",
            "report_delivery",
            delivery.id,
            metadata={"delivery_id": sent.id, "status": sent.status},
        )
    except Exception as exc:
        delivery.last_run_at = now
        delivery.last_error = str(exc) or exc.__class__.__name__
        if is_once:
            delivery.status = ERROR_STATUS
            delivery.next_run_at = None
        else:
            # Recorrente: mantem ativo e tenta de novo no proximo ciclo (ex.: Teams ainda nao configurado).
            delivery.next_run_at = compute_next_run(delivery, now + timedelta(seconds=1))
            if delivery.next_run_at is None:
                delivery.status = EXPIRED_STATUS
        delivery.updated_at = datetime.utcnow()
        db.commit()
        create_log(
            db,
            "error",
            f"Report delivery to Teams failed: {delivery.last_error}",
            "report_delivery",
            delivery.id,
        )


def run_due_report_deliveries_once(now: datetime | None = None, db: Session | None = None) -> int:
    own_session = db is None
    db = db or SessionLocal()
    triggered = 0
    try:
        hydrate_missing_report_delivery_next_runs(db, now)
        for delivery in due_report_deliveries(db, now):
            run_due_report_delivery(db, delivery, now)
            triggered += 1
        return triggered
    finally:
        if own_session:
            db.close()


def run_due_report_deliveries_for_all_environments(now: datetime | None = None) -> int:
    triggered = 0
    for environment in SUPPORTED_ENVIRONMENTS:
        with environment_scope(environment):
            db = session_for_environment(environment)
            try:
                triggered += run_due_report_deliveries_once(now, db)
            finally:
                db.close()
    return triggered


async def _runner_loop() -> None:
    interval = max(int(settings.SCHEDULE_POLL_INTERVAL_SECONDS or 5), 1)
    while True:
        try:
            await asyncio.to_thread(run_due_schedules_for_all_environments)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[schedule_runner] {exc}", flush=True)
        try:
            await asyncio.to_thread(run_due_report_deliveries_for_all_environments)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[schedule_runner:report_delivery] {exc}", flush=True)
        await asyncio.sleep(interval)


def start_schedule_runner() -> None:
    global _runner_task
    if _runner_task and not _runner_task.done():
        return
    _runner_task = asyncio.create_task(_runner_loop())


async def stop_schedule_runner() -> None:
    global _runner_task
    if not _runner_task:
        return
    _runner_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _runner_task
    _runner_task = None
