from __future__ import annotations

import json
from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.integration import IntegrationDelivery
from app.services.audit import create_log
from app.services.integrations.graph_client import (
    GraphClient,
    GraphConfigurationError,
    GraphIntegrationError,
    sanitize_for_storage,
    send_teams_webhook,
)


def _default_target() -> str:
    if str(getattr(settings, "MS_GRAPH_TEAMS_WEBHOOK_URL", "") or "").strip():
        return "Teams webhook"
    team_id = str(getattr(settings, "MS_GRAPH_TEAMS_TEAM_ID", "") or "").strip()
    channel_id = str(getattr(settings, "MS_GRAPH_TEAMS_CHANNEL_ID", "") or "").strip()
    return f"{team_id}/{channel_id}" if team_id and channel_id else "Teams"


def _parse_target(target: str | None) -> dict[str, str]:
    """Aceita 'team_id/channel_id' como override do canal (modo Graph)."""
    text = str(target or "").strip()
    if "/" in text:
        team_id, channel_id = text.split("/", 1)
        team_id = team_id.strip()
        channel_id = channel_id.strip()
        if team_id and channel_id:
            return {"team_id": team_id, "channel_id": channel_id}
    return {}


def build_report_summary(db: Session, report_type: str, filters: dict[str, Any]) -> dict[str, Any]:
    """Gera o resumo (contagens por secao + enviados com sucesso + tempo economizado)."""
    from app.routers.reports import (  # import tardio para evitar ciclo
        TIME_SAVED_MINUTES_PER_FILE,
        build_sections,
        format_dt,
        format_time_saved,
        parse_report_type,
        successful_files_count,
    )

    resolved_type = parse_report_type(report_type)
    sections = build_sections(db, resolved_type, filters)
    successful = successful_files_count(db, filters)
    total_min = round(successful * TIME_SAVED_MINUTES_PER_FILE)
    return {
        "report_type": resolved_type,
        "sections": [(section.title, len(section.rows)) for section in sections],
        "successful": successful,
        "time_saved_total": format_time_saved(total_min),
        "period_start": format_dt(filters.get("start")),
        "period_end": format_dt(filters.get("end")),
    }


def _period_label(summary: dict[str, Any]) -> str:
    start = summary.get("period_start") or "início"
    end = summary.get("period_end") or "agora"
    return f"{start} → {end}"


def render_text(message: str, summary: dict[str, Any]) -> str:
    lines = [str(message or "").strip()] if message else []
    lines.append("")
    lines.append(f"Relatório: {summary['report_type']}")
    lines.append(f"Período: {_period_label(summary)}")
    for title, count in summary["sections"]:
        lines.append(f"- {title}: {count}")
    lines.append(f"- Arquivos enviados (sucesso): {summary['successful']}")
    lines.append(f"- Tempo economizado total: {summary['time_saved_total']}")
    return "\n".join(line for line in lines if line is not None).strip()


def render_html(message: str, summary: dict[str, Any]) -> str:
    items = "".join(f"<li><b>{escape(str(title))}</b>: {escape(str(count))}</li>" for title, count in summary["sections"])
    items += f"<li><b>Arquivos enviados (sucesso)</b>: {escape(str(summary['successful']))}</li>"
    items += f"<li><b>Tempo economizado total</b>: {escape(str(summary['time_saved_total']))}</li>"
    message_block = f"<p>{escape(str(message))}</p>" if message else ""
    return (
        f"{message_block}"
        f"<p><b>{escape(str(summary['report_type']))}</b> — {escape(_period_label(summary))}</p>"
        f"<ul>{items}</ul>"
    )


def send_report_to_teams(
    db: Session,
    *,
    report_type: str,
    filters: dict[str, Any],
    message: str,
    target: str | None = None,
    created_by_id: int | None = None,
) -> IntegrationDelivery:
    """Monta o resumo do relatorio e envia ao Teams (webhook ou Graph), registrando o IntegrationDelivery."""
    summary = build_report_summary(db, report_type, filters)
    text_content = render_text(message, summary)
    html_content = render_html(message, summary)
    resolved_target = str(target or "").strip() or _default_target()

    delivery = IntegrationDelivery(
        provider="Teams",
        delivery_type="report",
        target=resolved_target,
        subject=summary["report_type"],
        status="pending",
        request_json=json.dumps(sanitize_for_storage({"report_type": summary["report_type"], "message": message, "summary": summary}), ensure_ascii=False, default=str),
        created_by_id=created_by_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    try:
        if str(getattr(settings, "MS_GRAPH_TEAMS_WEBHOOK_URL", "") or "").strip():
            result = send_teams_webhook({"content": text_content}, settings)
        else:
            payload = {"content": html_content, "content_type": "html", **_parse_target(target)}
            result = GraphClient(settings).send_channel_message(payload)
        delivery.status = "sent"
        delivery.response_json = json.dumps(sanitize_for_storage(result.data), ensure_ascii=False, default=str)
        delivery.error_message = None
        delivery.sent_at = datetime.utcnow()
        delivery.failed_at = None
        delivery.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(delivery)
        create_log(
            db,
            "info",
            f"Report delivery sent to Teams: {summary['report_type']}",
            "integration_delivery",
            delivery.id,
            metadata={"provider": "Teams", "delivery_type": "report", "target": resolved_target},
        )
        return delivery
    except GraphIntegrationError as exc:
        delivery.status = "not_configured" if isinstance(exc, GraphConfigurationError) else "failed"
        delivery.error_message = exc.message
        delivery.response_json = json.dumps(sanitize_for_storage(exc.details), ensure_ascii=False, default=str)
        delivery.failed_at = datetime.utcnow()
        delivery.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(delivery)
        create_log(
            db,
            "warning" if isinstance(exc, GraphConfigurationError) else "error",
            f"Report delivery to Teams {delivery.status}: {summary['report_type']}",
            "integration_delivery",
            delivery.id,
            metadata={"provider": "Teams", "delivery_type": "report", "target": resolved_target, "error": exc.message},
        )
        raise
