import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezone import now_sao_paulo_naive, sao_paulo_local_iso, sao_paulo_utc_iso, to_sao_paulo_naive
from app.db.session import get_db
from app.models.integration import IntegrationConnection, IntegrationDelivery
from app.models.report_delivery import ReportDelivery
from app.routers.reports import filters_from_payload, parse_report_type
from app.services.audit import create_log
from app.services.integrations.graph_client import (
    GraphClient,
    GraphConfigurationError,
    GraphIntegrationError,
    build_graph_status,
    missing_base_graph_settings,
    sanitize_for_storage,
    send_teams_webhook,
)
from app.services.integrations.report_teams import send_report_to_teams
from app.services.schedule_runner import (
    ACTIVE_STATUS,
    PAUSED_STATUS,
    compute_next_run,
    display_status,
    normalize_status,
    parse_local_datetime,
    run_due_report_delivery,
)

router = APIRouter()


@router.get("")
def list_integrations(db: Session = Depends(get_db)):
    return db.query(IntegrationConnection).filter(IntegrationConnection.is_deleted == False).all()


@router.get("/graph/status")
def graph_status():
    return build_graph_status(settings)


@router.get("/deliveries")
def integration_deliveries(
    limit: int = Query(10, ge=1, le=100),
    provider: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(IntegrationDelivery)
    if provider:
        query = query.filter(IntegrationDelivery.provider == provider)
    if status:
        query = query.filter(IntegrationDelivery.status == status)
    deliveries = query.order_by(IntegrationDelivery.created_at.desc(), IntegrationDelivery.id.desc()).limit(limit).all()
    return [_delivery_response(delivery) for delivery in deliveries]


@router.post("/graph/test")
def test_graph_connection():
    status = build_graph_status(settings)
    if not status["configured"]:
        return {"status": "not_configured", "provider": "Microsoft Graph", "missing": status["missing"]}
    try:
        result = GraphClient(settings).test_connection()
        return {
            "status": "connected",
            "provider": "Microsoft Graph",
            "request_id": result.request_id,
            "account": result.data,
        }
    except GraphIntegrationError as exc:
        raise _http_error(exc) from exc


@router.post("/teams/messages")
def send_teams_message(data: dict, db: Session = Depends(get_db)):
    content = str(data.get("content") or data.get("message") or "").strip()
    if not content:
        raise HTTPException(422, "Mensagem Teams vazia.")

    target = str(data.get("target") or data.get("channel") or "").strip()
    if not target:
        target = _teams_default_target()
    request_payload = {**data, "content": content, "target": target}
    delivery = _create_delivery(db, "Teams", "message", target, data.get("event"), request_payload)
    try:
        if str(settings.MS_GRAPH_TEAMS_WEBHOOK_URL or "").strip():
            result = send_teams_webhook(request_payload, settings)
        else:
            _ensure_teams_graph_message_configured()
            result = GraphClient(settings).send_channel_message(request_payload)
        _finish_delivery(db, delivery, "sent", result.data)
        return {"status": "sent", "channel": "teams", "delivery": _delivery_response(delivery)}
    except GraphIntegrationError as exc:
        _fail_delivery(db, delivery, exc)
        raise _http_error(exc) from exc


@router.post("/outlook/email")
def send_outlook_email(data: dict, db: Session = Depends(get_db)):
    recipients = _normalize_recipients(data.get("to_recipients") or data.get("to") or data.get("recipients"))
    if not recipients:
        raise HTTPException(422, "Informe pelo menos um destinatario.")
    subject = str(data.get("subject") or "").strip()
    if not subject:
        raise HTTPException(422, "Informe o assunto do e-mail.")

    request_payload = {
        **data,
        "to_recipients": recipients,
        "subject": subject,
        "body": str(data.get("body") or ""),
        "body_content_type": str(data.get("body_content_type") or "HTML"),
    }
    delivery = _create_delivery(db, "Outlook", "email", _recipient_target(recipients), subject, request_payload)
    try:
        result = GraphClient(settings).send_mail(
            to_recipients=recipients,
            subject=subject,
            body=request_payload["body"],
            body_content_type=request_payload["body_content_type"],
        )
        _finish_delivery(db, delivery, "sent", result.data)
        return {"status": "sent", "channel": "outlook", "delivery": _delivery_response(delivery)}
    except GraphIntegrationError as exc:
        _fail_delivery(db, delivery, exc)
        raise _http_error(exc) from exc


@router.post("/outlook/events")
def create_outlook_event(data: dict, db: Session = Depends(get_db)):
    request_payload = _event_request_payload(data)
    delivery = _create_delivery(
        db,
        "Outlook",
        "event",
        _recipient_target(request_payload.get("attendees") or []),
        request_payload["subject"],
        request_payload,
    )
    try:
        result = GraphClient(settings).create_calendar_event(request_payload, online_meeting=False)
        _finish_delivery(db, delivery, "created", result.data)
        return {"status": "created", "channel": "outlook", "delivery": _delivery_response(delivery)}
    except GraphIntegrationError as exc:
        _fail_delivery(db, delivery, exc)
        raise _http_error(exc) from exc


@router.post("/teams/calendar")
def create_teams_calendar_event(data: dict, db: Session = Depends(get_db)):
    request_payload = _event_request_payload(data)
    delivery = _create_delivery(
        db,
        "Teams",
        "calendar",
        _recipient_target(request_payload.get("attendees") or []),
        request_payload["subject"],
        request_payload,
    )
    try:
        result = GraphClient(settings).create_calendar_event(request_payload, online_meeting=True)
        _finish_delivery(db, delivery, "created", result.data)
        return {"status": "created", "channel": "teams", "delivery": _delivery_response(delivery)}
    except GraphIntegrationError as exc:
        _fail_delivery(db, delivery, exc)
        raise _http_error(exc) from exc


@router.post("/{provider}/link")
def link_integration(provider: str, data: dict | None = None, db: Session = Depends(get_db)):
    data = data or {}
    conn = IntegrationConnection(provider=provider, account_label=data.get("account_label"), linked_at=datetime.utcnow())
    db.add(conn)
    db.commit()
    db.refresh(conn)
    create_log(db, "info", f"Integration linked: {provider}", "integration", conn.id)
    return conn


@router.post("/{provider}/unlink")
def unlink_integration(provider: str, db: Session = Depends(get_db)):
    conn = db.query(IntegrationConnection).filter(IntegrationConnection.provider == provider, IntegrationConnection.is_deleted == False).first()
    if not conn:
        raise HTTPException(404)
    conn.is_deleted = True
    conn.unlinked_at = datetime.utcnow()
    db.commit()
    create_log(db, "warning", f"Integration unlinked: {provider}", "integration", conn.id)
    return {"status": "unlinked"}


def _create_delivery(
    db: Session,
    provider: str,
    delivery_type: str,
    target: str | None,
    subject: str | None,
    request_payload: dict[str, Any],
) -> IntegrationDelivery:
    delivery = IntegrationDelivery(
        provider=provider,
        delivery_type=delivery_type,
        target=target,
        subject=subject,
        status="pending",
        request_json=_json_dumps(sanitize_for_storage(request_payload)),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return delivery


def _finish_delivery(db: Session, delivery: IntegrationDelivery, status: str, response_payload: Any) -> None:
    delivery.status = status
    delivery.response_json = _json_dumps(sanitize_for_storage(response_payload))
    delivery.error_message = None
    delivery.sent_at = datetime.utcnow()
    delivery.failed_at = None
    delivery.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(delivery)
    create_log(
        db,
        "info",
        f"Integration delivery {status}: {delivery.provider} {delivery.delivery_type}",
        "integration_delivery",
        delivery.id,
        metadata={"provider": delivery.provider, "delivery_type": delivery.delivery_type, "target": delivery.target},
    )


def _fail_delivery(db: Session, delivery: IntegrationDelivery, exc: GraphIntegrationError) -> None:
    delivery.status = "not_configured" if isinstance(exc, GraphConfigurationError) else "failed"
    delivery.error_message = exc.message
    delivery.response_json = _json_dumps(sanitize_for_storage(exc.details))
    delivery.failed_at = datetime.utcnow()
    delivery.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(delivery)
    create_log(
        db,
        "warning" if isinstance(exc, GraphConfigurationError) else "error",
        f"Integration delivery {delivery.status}: {delivery.provider} {delivery.delivery_type}",
        "integration_delivery",
        delivery.id,
        metadata={"provider": delivery.provider, "delivery_type": delivery.delivery_type, "target": delivery.target, "error": exc.message},
    )


def _delivery_response(delivery: IntegrationDelivery) -> dict[str, Any]:
    return {
        "id": delivery.id,
        "provider": delivery.provider,
        "delivery_type": delivery.delivery_type,
        "target": delivery.target,
        "subject": delivery.subject,
        "status": delivery.status,
        "error_message": delivery.error_message,
        "created_at": delivery.created_at,
        "updated_at": delivery.updated_at,
        "sent_at": delivery.sent_at,
        "failed_at": delivery.failed_at,
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _http_error(exc: GraphIntegrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _normalize_recipients(value: Any) -> list[dict[str, str]]:
    items: list[Any]
    if isinstance(value, str):
        items = [item.strip() for item in value.replace(";", ",").split(",")]
    elif isinstance(value, list):
        items = value
    elif value:
        items = [value]
    else:
        items = []

    recipients: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, str):
            address = item.strip()
            name = ""
        elif isinstance(item, dict):
            address = str(item.get("address") or item.get("email") or "").strip()
            name = str(item.get("name") or "").strip()
        else:
            continue
        if address:
            recipient: dict[str, str] = {"address": address}
            if name:
                recipient["name"] = name
            recipients.append(recipient)
    return recipients


def _recipient_target(recipients: list[dict[str, str]]) -> str:
    addresses = [recipient.get("address", "") for recipient in recipients if recipient.get("address")]
    return ", ".join(addresses) if addresses else "-"


def _event_request_payload(data: dict[str, Any]) -> dict[str, Any]:
    subject = str(data.get("subject") or data.get("title") or "").strip()
    start = str(data.get("start_datetime") or data.get("start") or "").strip()
    end = str(data.get("end_datetime") or data.get("end") or "").strip()
    if not subject:
        raise HTTPException(422, "Informe o titulo do evento.")
    if not start or not end:
        raise HTTPException(422, "Informe inicio e fim do evento.")
    return {
        **data,
        "subject": subject,
        "body": str(data.get("body") or ""),
        "body_content_type": str(data.get("body_content_type") or "HTML"),
        "start_datetime": start,
        "end_datetime": end,
        "attendees": _normalize_recipients(data.get("attendees") or data.get("to_recipients") or []),
    }


def _teams_default_target() -> str:
    if str(settings.MS_GRAPH_TEAMS_WEBHOOK_URL or "").strip():
        return "Teams webhook"
    team_id = str(settings.MS_GRAPH_TEAMS_TEAM_ID or "").strip()
    channel_id = str(settings.MS_GRAPH_TEAMS_CHANNEL_ID or "").strip()
    if team_id and channel_id:
        return f"{team_id}/{channel_id}"
    return "Teams"


def _ensure_teams_graph_message_configured() -> None:
    missing = missing_base_graph_settings(settings)
    if not str(settings.MS_GRAPH_TEAMS_TEAM_ID or "").strip():
        missing.append("MS_GRAPH_TEAMS_TEAM_ID")
    if not str(settings.MS_GRAPH_TEAMS_CHANNEL_ID or "").strip():
        missing.append("MS_GRAPH_TEAMS_CHANNEL_ID")
    if missing:
        raise GraphConfigurationError(missing)


# ===================== Agendamento de envio de relatorio ao Teams =====================

REPORT_DELIVERY_FREQUENCIES = {"daily", "weekly", "monthly", "once", "interval"}


def _safe_int_or_none(value: Any) -> int | None:
    if value in [None, "", "Todos"]:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _report_delivery_payload(data: dict) -> dict:
    data = data or {}
    clean: dict[str, Any] = {}
    if data.get("report_type") is not None:
        clean["report_type"] = parse_report_type(data.get("report_type"))  # valida e normaliza o nome
    if data.get("file_format") is not None:
        clean["file_format"] = str(data.get("file_format") or "xlsx").strip().lower() or "xlsx"
    if "message" in data:
        clean["message"] = str(data.get("message") or "")
    if "name" in data:
        clean["name"] = str(data.get("name") or "").strip() or None
    if "target" in data or "channel" in data:
        clean["target"] = str(data.get("target") or data.get("channel") or "").strip() or None
    if "period_days" in data:
        clean["period_days"] = _safe_int_or_none(data.get("period_days"))
    if "automation_id" in data:
        clean["automation_id"] = _safe_int_or_none(data.get("automation_id"))
    if "workspace_id" in data:
        clean["workspace_id"] = _safe_int_or_none(data.get("workspace_id"))

    frequency_type = str(data.get("frequency_type") or "").strip().lower()
    if frequency_type:
        clean["frequency_type"] = frequency_type
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    if "time_of_day" in data:
        clean["time_of_day"] = data.get("time_of_day")
    elif payload.get("hour"):
        clean["time_of_day"] = payload.get("hour")
    if "days_of_week" in data:
        days = data.get("days_of_week")
        clean["days_of_week"] = days if isinstance(days, str) else json.dumps(days, ensure_ascii=False)
    elif "week_days" in payload:
        clean["days_of_week"] = json.dumps(payload.get("week_days"), ensure_ascii=False)
    if "day_of_month" in data:
        clean["day_of_month"] = _safe_int_or_none(data.get("day_of_month"))
    elif "month_day" in payload:
        clean["day_of_month"] = _safe_int_or_none(payload.get("month_day"))
    if "interval_minutes" in data:
        interval = _safe_int_or_none(data.get("interval_minutes"))
        clean["interval_minutes"] = max(interval, 1) if interval is not None else None

    start = data.get("start_date") if "start_date" in data else data.get("starts_at")
    end = data.get("end_date") if "end_date" in data else data.get("expires_at")
    if start is not None:
        clean["start_date"] = parse_local_datetime(start)
    if end is not None:
        clean["end_date"] = parse_local_datetime(end)
    if data.get("run_date") is not None:
        clean["run_date"] = parse_local_datetime(data.get("run_date"))
    if clean.get("frequency_type") == "once" and clean.get("start_date") and not clean.get("run_date"):
        clean["run_date"] = clean["start_date"]
    if "status" in data:
        clean["status"] = normalize_status(data.get("status"))
    return clean


def _validate_report_delivery(delivery: ReportDelivery, now: datetime | None = None) -> None:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    if delivery.frequency_type not in REPORT_DELIVERY_FREQUENCIES:
        raise HTTPException(422, "Invalid frequency_type")
    if not delivery.report_type:
        raise HTTPException(422, "report_type is required")
    if delivery.frequency_type == "once":
        delivery.run_date = delivery.run_date or delivery.start_date
        delivery.start_date = delivery.start_date or delivery.run_date
        if not delivery.run_date:
            raise HTTPException(422, "Data e Hora is required")
        if delivery.run_date <= now:
            raise HTTPException(422, "Data e Hora must be in the future")
    if delivery.frequency_type == "interval" and not delivery.interval_minutes:
        delivery.interval_minutes = 60


def _refresh_report_delivery(delivery: ReportDelivery) -> None:
    delivery.name = delivery.name or f"Teams: {delivery.report_type}"
    delivery.next_run_at = compute_next_run(delivery)
    if (
        normalize_status(delivery.status) == ACTIVE_STATUS
        and delivery.next_run_at is None
        and delivery.end_date
        and delivery.end_date < now_sao_paulo_naive()
    ):
        delivery.status = "expired"


def _report_delivery_out(delivery: ReportDelivery) -> dict[str, Any]:
    return {
        "id": delivery.id,
        "name": delivery.name,
        "provider": delivery.provider or "Teams",
        "report_type": delivery.report_type,
        "file_format": delivery.file_format,
        "message": delivery.message,
        "target": delivery.target,
        "automation_id": delivery.automation_id,
        "workspace_id": delivery.workspace_id,
        "period_days": delivery.period_days,
        "frequency_type": delivery.frequency_type,
        "time_of_day": delivery.time_of_day,
        "hour": delivery.time_of_day,
        "days_of_week": delivery.days_of_week,
        "day_of_month": delivery.day_of_month,
        "month_day": delivery.day_of_month,
        "run_date": sao_paulo_local_iso(delivery.run_date),
        "start_date": sao_paulo_local_iso(delivery.start_date),
        "starts_at": sao_paulo_local_iso(delivery.start_date),
        "end_date": sao_paulo_local_iso(delivery.end_date),
        "expires_at": sao_paulo_local_iso(delivery.end_date),
        "interval_minutes": delivery.interval_minutes,
        "next_run_at": sao_paulo_local_iso(delivery.next_run_at),
        "last_run_at": sao_paulo_local_iso(delivery.last_run_at),
        "last_delivery_id": delivery.last_delivery_id,
        "last_error": delivery.last_error,
        "status": display_status(delivery),
        "raw_status": delivery.status,
        "created_at": sao_paulo_utc_iso(delivery.created_at),
        "updated_at": sao_paulo_utc_iso(delivery.updated_at),
    }


@router.get("/teams/report-deliveries")
def list_report_deliveries(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    deliveries = (
        db.query(ReportDelivery)
        .filter(ReportDelivery.is_deleted == False)
        .order_by(ReportDelivery.next_run_at.is_(None), ReportDelivery.next_run_at.asc(), ReportDelivery.id.desc())
        .limit(limit)
        .all()
    )
    return [_report_delivery_out(delivery) for delivery in deliveries]


@router.post("/teams/report-deliveries")
def create_report_delivery(data: dict, db: Session = Depends(get_db)):
    clean = _report_delivery_payload(data)
    clean["status"] = clean.get("status") or ACTIVE_STATUS
    clean.setdefault("report_type", parse_report_type(None))
    delivery = ReportDelivery(provider="Teams", created_by_id=_safe_int_or_none(data.get("generated_by_id")), **clean)
    _validate_report_delivery(delivery)
    _refresh_report_delivery(delivery)
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    create_log(db, "info", f"Report delivery created: {delivery.name}", "report_delivery", delivery.id)
    return _report_delivery_out(delivery)


@router.put("/teams/report-deliveries/{id}")
def update_report_delivery(id: int, data: dict, db: Session = Depends(get_db)):
    delivery = db.query(ReportDelivery).filter(ReportDelivery.id == id, ReportDelivery.is_deleted == False).first()
    if not delivery:
        raise HTTPException(404)
    for key, value in _report_delivery_payload(data).items():
        setattr(delivery, key, value)
    delivery.last_error = None
    if delivery.status not in {PAUSED_STATUS, "completed"}:
        delivery.status = normalize_status(delivery.status)
    _validate_report_delivery(delivery)
    _refresh_report_delivery(delivery)
    db.commit()
    db.refresh(delivery)
    create_log(db, "info", f"Report delivery updated: {delivery.name}", "report_delivery", delivery.id)
    return _report_delivery_out(delivery)


@router.delete("/teams/report-deliveries/{id}")
def delete_report_delivery(id: int, db: Session = Depends(get_db)):
    delivery = db.query(ReportDelivery).filter(ReportDelivery.id == id, ReportDelivery.is_deleted == False).first()
    if not delivery:
        raise HTTPException(404)
    delivery.is_deleted = True
    delivery.deleted_at = datetime.utcnow()
    db.commit()
    create_log(db, "warning", "Report delivery deleted", "report_delivery", delivery.id)
    return {"status": "deleted"}


@router.post("/teams/report-deliveries/{id}/actions/{action}")
def report_delivery_action(id: int, action: str, db: Session = Depends(get_db)):
    delivery = db.query(ReportDelivery).filter(ReportDelivery.id == id, ReportDelivery.is_deleted == False).first()
    if not delivery:
        raise HTTPException(404)
    if action == "pause":
        delivery.status = PAUSED_STATUS
        delivery.next_run_at = None
        db.commit()
        db.refresh(delivery)
        create_log(db, "info", "Report delivery paused", "report_delivery", delivery.id)
        return _report_delivery_out(delivery)
    if action == "resume":
        delivery.status = ACTIVE_STATUS
        delivery.last_error = None
        _validate_report_delivery(delivery)
        _refresh_report_delivery(delivery)
        db.commit()
        db.refresh(delivery)
        create_log(db, "info", "Report delivery resumed", "report_delivery", delivery.id)
        return _report_delivery_out(delivery)
    if action == "delete":
        return delete_report_delivery(id, db)
    if action in {"run-now", "run_now"}:
        run_due_report_delivery(db, delivery)
        db.refresh(delivery)
        return _report_delivery_out(delivery)
    raise HTTPException(400, "Invalid action")


@router.post("/teams/report-deliveries/send-now")
def send_report_delivery_now(data: dict, db: Session = Depends(get_db)):
    """Envia o resumo do relatorio ao Teams imediatamente, sem persistir agendamento."""
    report_type = parse_report_type(data.get("report_type"))
    filters = filters_from_payload(data)
    message = str(data.get("message") or "")
    target = str(data.get("target") or data.get("channel") or "").strip() or None
    try:
        delivery = send_report_to_teams(
            db,
            report_type=report_type,
            filters=filters,
            message=message,
            target=target,
            created_by_id=_safe_int_or_none(data.get("generated_by_id")),
        )
    except GraphIntegrationError as exc:
        raise _http_error(exc) from exc
    return {"status": delivery.status, "channel": "teams", "delivery": _delivery_response(delivery)}
