import base64
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.integration import IntegrationConnection, IntegrationDelivery
from app.routers.reports import (
    _render_report_image_threaded,
    compute_card_image_data,
    report_delivery_bundle,
    write_report_to_delivery_folder,
)
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


@router.post("/reports/{report_id}/email")
def send_report_email(report_id: int, data: dict, db: Session = Depends(get_db)):
    recipients = _normalize_recipients(data.get("to_recipients") or data.get("to") or data.get("recipients"))
    if not recipients:
        raise HTTPException(422, "Informe pelo menos um destinatario.")
    bundle = report_delivery_bundle(db, report_id)
    rep = bundle["report"]
    subject = str(data.get("subject") or "").strip() or f"Relatório Automation HUB: {rep.name}"
    body = str(data.get("body") or "").strip() or bundle["summary"]
    content_bytes = base64.b64encode(bundle["content"]).decode("ascii")

    request_payload = {
        "report_id": report_id,
        "filename": bundle["filename"],
        "recipients": recipients,
        "subject": subject,
    }
    delivery = _create_delivery(db, "Outlook", "report_email", _recipient_target(recipients), subject, request_payload)
    try:
        result = GraphClient(settings).send_mail(
            to_recipients=recipients,
            subject=subject,
            body=body,
            body_content_type="HTML",
            attachments=[{
                "name": bundle["filename"],
                "content_bytes": content_bytes,
                "content_type": bundle["media_type"],
            }],
        )
        _finish_delivery(db, delivery, "sent", result.data)
        return {"status": "sent", "channel": "outlook", "delivery": _delivery_response(delivery)}
    except GraphIntegrationError as exc:
        _fail_delivery(db, delivery, exc)
        raise _http_error(exc) from exc


@router.post("/reports/{report_id}/teams")
def send_report_teams(report_id: int, data: dict, request: Request, db: Session = Depends(get_db)):
    bundle = report_delivery_bundle(db, report_id)
    rep = bundle["report"]
    download_url = str(data.get("download_url") or "").strip() or f"{str(request.base_url).rstrip('/')}/api/reports/{report_id}/download"
    content = str(data.get("content") or "").strip() or f"{bundle['summary']}\n\nDownload: {download_url}"

    target = str(data.get("target") or data.get("channel") or "").strip()
    if not target:
        target = _teams_default_target()
    request_payload = {**data, "content": content, "target": target}
    delivery = _create_delivery(db, "Teams", "report_teams", target, rep.name, request_payload)
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


@router.post("/reports/{report_id}/teams-image")
def send_report_teams_image(report_id: int, data: dict, request: Request, db: Session = Depends(get_db)):
    """Envio DIRETO do card semanal (imagem + botoes) via Microsoft Graph -- ALTERNATIVA ADITIVA ao
    fluxo do Power Automate (GUIA_POWER_AUTOMATE.md, Parte I). Nao remove nem altera /deliver-folder
    nem /reports/{id}/teams; e um caminho a mais, pensado para resolver o ponto fragil documentado no
    guia: o link de compartilhamento do OneDrive (+ '&download=1') as vezes nao devolve os bytes do
    PNG e a imagem nao renderiza no Teams.

    Aqui a imagem viaja embutida na propria mensagem (Microsoft Graph `hostedContents`, ate 4 MB),
    sem depender de OneDrive/SharePoint. Requer o Graph configurado (MS_GRAPH_*) e o app registrado
    com permissao de aplicativo para postar no canal (mesma config ja usada por /teams/messages).

    IMPORTANTE: so funciona para CANAIS de Equipe (credencial de aplicativo). Nao funciona para
    chats 1:1/grupo (ex.: "1:1 Ederson") -- a Microsoft nao permite postar em chats com credencial
    de aplicativo, so com login delegado de usuario ou um Bot. Para esse caso, ver
    RECOMENDACAO_TEAMS_IMAGEM_GRAPH.md, Secao 6 (links diretos do backend + Power Automate).

    Botao "Solicitar Acesso": aponta (Action.OpenUrl) para REPORT_CARD_ACCESS_URL -- o link do
    fluxo "Solicitar acesso - Teams" (Parte III do guia).
    """
    bundle = report_delivery_bundle(db, report_id)
    rep = bundle["report"]
    image_data = bundle.get("image_data") or compute_card_image_data(db)

    tmp_dir = Path(tempfile.mkdtemp(prefix="teams_graph_image_"))
    image_path = _render_report_image_threaded(image_data, tmp_dir / f"report_{report_id}.png")
    if image_path is None:
        raise HTTPException(502, "Nao foi possivel gerar a imagem do relatorio (Chromium/Playwright offline indisponivel).")
    image_bytes = image_path.read_bytes()

    download_url = str(data.get("download_url") or "").strip() or f"{str(request.base_url).rstrip('/')}/api/reports/{report_id}/download"
    playground_url = str(settings.REPORT_CARD_PLAYGROUND_URL or settings.PLAYGROUND_URL or "").strip()
    access_url = str(data.get("access_url") or settings.REPORT_CARD_ACCESS_URL or "").strip()

    actions: list[dict[str, Any]] = []
    if playground_url:
        actions.append({"type": "Action.OpenUrl", "title": "Abrir Playground", "url": playground_url})
    if access_url:
        actions.append({"type": "Action.OpenUrl", "title": "Solicitar Acesso", "url": access_url})
    actions.append({"type": "Action.OpenUrl", "title": "Baixar Relatório (PDF)", "url": download_url})
    adaptive_card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": [],
        "actions": actions,
    }

    team_id = str(data.get("team_id") or settings.MS_GRAPH_TEAMS_TEAM_ID or "").strip()
    channel_id = str(data.get("channel_id") or settings.MS_GRAPH_TEAMS_CHANNEL_ID or "").strip()
    target = f"{team_id or '-'}/{channel_id or '-'}"
    request_payload = {"report_id": report_id, "target": target, "download_url": download_url}
    delivery = _create_delivery(db, "Teams", "report_teams_image", target, rep.name, request_payload)
    try:
        result = GraphClient(settings).send_channel_message_with_image_card(
            team_id=team_id,
            channel_id=channel_id,
            image_bytes=image_bytes,
            adaptive_card=adaptive_card,
        )
        _finish_delivery(db, delivery, "sent", result.data)
        return {"status": "sent", "channel": "teams_graph_image", "delivery": _delivery_response(delivery)}
    except GraphIntegrationError as exc:
        _fail_delivery(db, delivery, exc)
        raise _http_error(exc) from exc


@router.post("/reports/{report_id}/deliver-folder")
def deliver_report_to_folder(report_id: int, data: dict, db: Session = Depends(get_db)):
    bundle = report_delivery_bundle(db, report_id)
    rep = bundle["report"]
    routing = {k: data.get(k) for k in ("teams_channel", "email_to", "subject") if data.get(k)}
    target = str(settings.REPORT_DELIVERY_PATH or "").strip() or "-"
    request_payload = {"report_id": report_id, "filename": bundle["filename"], "routing": routing}
    delivery = _create_delivery(db, "PowerAutomate", "report_folder", target, rep.name, request_payload)
    try:
        path = write_report_to_delivery_folder(bundle, routing=routing)
        if path is None:
            raise GraphConfigurationError(["REPORT_DELIVERY_PATH"], "Pasta de entrega (REPORT_DELIVERY_PATH) nao configurada.")
        _finish_delivery(db, delivery, "sent", {"delivery_path": str(path)})
        return {"status": "sent", "channel": "power_automate", "delivery": _delivery_response(delivery)}
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
