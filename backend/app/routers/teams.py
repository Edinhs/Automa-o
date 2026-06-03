import ipaddress
import json
import requests
import calendar
from datetime import datetime, time, timedelta
from typing import Any, List
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db.session import get_db
from app.models.teams import TeamsChannel, TeamsReportSchedule
from app.models.execution import ExecutionReport
from app.services.audit import create_log
from app.core.timezone import now_sao_paulo_naive, to_sao_paulo_naive

router = APIRouter()

# --- Funções Auxiliares de Envio para o Teams ---

def validate_webhook_url(webhook_url: str | None) -> str:
    """Exige https:// e bloqueia hosts internos (loopback/privados) — mitiga SSRF.

    Webhooks de Incoming Connectors do Teams sempre sao https em dominios publicos
    (ex.: *.webhook.office.com). Recusar http e IPs privados evita que um webhook
    forjado faca o backend bater em servicos internos.
    """
    url = str(webhook_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Webhook do Teams deve ser uma URL https:// válida.")
    host = parsed.hostname
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(status_code=400, detail="Webhook do Teams não pode apontar para endereço interno.")
    except ValueError:
        # hostname (nao e IP literal): bloqueia apenas localhost explicito
        if host.lower() in {"localhost", "localhost.localdomain"}:
            raise HTTPException(status_code=400, detail="Webhook do Teams não pode apontar para localhost.")
    return url


def send_adaptive_card_to_teams(webhook_url: str, card_payload: dict):
    safe_url = validate_webhook_url(webhook_url)
    try:
        response = requests.post(
            safe_url,
            json=card_payload,
            timeout=20
        )
        if response.status_code not in (200, 202) and "1" not in response.text:
            # Algumas respostas de Incoming Webhooks retornam apenas "1" e status 200
            raise Exception(f"Teams retornou HTTP {response.status_code}: {response.text}")
        return True
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Erro ao enviar notificação ao Teams: {str(exc)}")

def build_report_adaptive_card(
    report_name: str,
    report_type: str,
    file_format: str,
    generated_at: str,
    download_url: str,
    period_label: str = "Não especificado"
) -> dict:
    # Cores e identidade base Stellantis
    # Formato do Adaptive Card
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "Container",
                            "style": "accent",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": "📊 Stellantis Automation HUB",
                                    "weight": "Bolder",
                                    "size": "Medium",
                                    "color": "Accent"
                                },
                                {
                                    "type": "TextBlock",
                                    "text": "Relatório Executivo Disponível",
                                    "isSubtle": True,
                                    "spacing": "None"
                                }
                            ]
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                { "title": "Relatório:", "value": report_name },
                                { "title": "Tipo:", "value": report_type },
                                { "title": "Formato:", "value": file_format.upper() },
                                { "title": "Período:", "value": period_label },
                                { "title": "Gerado em:", "value": generated_at }
                            ],
                            "spacing": "Medium"
                        },
                        {
                            "type": "TextBlock",
                            "text": "O arquivo foi processado com sucesso pelo HUB e está disponível para download imediato abaixo.",
                            "wrap": True,
                            "spacing": "Medium"
                        }
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "📥 Baixar Relatório",
                            "url": download_url
                        }
                    ]
                }
            }
        ]
    }

# --- Funções de Cálculo de Próxima Execução ---

def parse_time_of_day(value: str | None) -> time:
    raw = str(value or "08:00").strip()
    try:
        hour, minute = raw.split(":", 1)
        return time(hour=int(hour), minute=int(minute[:2]))
    except Exception:
        return time(hour=8, minute=0)

def parse_weekdays(raw: str | None) -> List[int]:
    if not raw:
        return []
    try:
        values = json.loads(raw)
        if isinstance(values, list):
            return [int(v) for v in values]
    except Exception:
        pass
    return []

def compute_report_next_run(schedule: TeamsReportSchedule, now: datetime | None = None) -> datetime | None:
    now = to_sao_paulo_naive(now) or now_sao_paulo_naive()
    frequency = str(schedule.frequency_type or "").strip().lower()
    
    if schedule.status != "active":
        return None
        
    if frequency == "once":
        if schedule.last_run_at:
            return None
        return schedule.run_date if schedule.run_date and schedule.run_date >= now else None
        
    run_time = parse_time_of_day(schedule.time_of_day)
    
    if frequency == "daily":
        candidate = datetime.combine(now.date(), run_time)
        if candidate < now:
            candidate += timedelta(days=1)
        return candidate
        
    if frequency == "weekly":
        days = parse_weekdays(schedule.days_of_week)
        if not days:
            days = [now.weekday()]
        for offset in range(0, 15):
            day = now + timedelta(days=offset)
            if day.weekday() in days:
                candidate = datetime.combine(day.date(), run_time)
                if candidate >= now:
                    return candidate
        return None
        
    if frequency == "monthly":
        requested_day = max(int(schedule.day_of_month or 1), 1)
        year = now.year
        month = now.month
        for _ in range(0, 18):
            last_day = calendar.monthrange(year, month)[1]
            day = min(requested_day, last_day)
            candidate = datetime.combine(datetime(year, month, day).date(), run_time)
            if candidate >= now:
                return candidate
            month += 1
            if month > 12:
                month = 1
                year += 1
        return None
        
    return None

# --- Rotas de Canais do Teams ---

@router.get("/channels")
def list_teams_channels(db: Session = Depends(get_db)):
    return db.query(TeamsChannel).filter(TeamsChannel.is_deleted == False).order_by(TeamsChannel.id.desc()).all()

@router.post("/channels")
def create_teams_channel(data: dict, db: Session = Depends(get_db)):
    name = str(data.get("name") or "").strip()
    webhook_url = str(data.get("webhook_url") or "").strip()
    if not name or not webhook_url:
        raise HTTPException(422, detail="Nome do canal e URL do webhook são obrigatórios.")
    webhook_url = validate_webhook_url(webhook_url)

    channel = TeamsChannel(name=name, webhook_url=webhook_url)
    db.add(channel)
    db.commit()
    db.refresh(channel)
    create_log(db, "info", f"Canal do Teams cadastrado: {name}", "teams_channel", channel.id)
    return channel

@router.delete("/channels/{id}")
def delete_teams_channel(id: int, db: Session = Depends(get_db)):
    channel = db.query(TeamsChannel).filter(TeamsChannel.id == id, TeamsChannel.is_deleted == False).first()
    if not channel:
        raise HTTPException(404, detail="Canal não encontrado.")
    channel.is_deleted = True
    channel.status = "inactive"
    db.commit()
    create_log(db, "warning", f"Canal do Teams removido: {channel.name}", "teams_channel", channel.id)
    return {"status": "deleted"}

@router.post("/channels/{id}/test")
def test_teams_channel(id: int, db: Session = Depends(get_db)):
    channel = db.query(TeamsChannel).filter(TeamsChannel.id == id, TeamsChannel.is_deleted == False).first()
    if not channel:
        raise HTTPException(404, detail="Canal não encontrado.")
        
    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "Container",
                            "style": "good",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": "✅ Stellantis Automation HUB",
                                    "weight": "Bolder",
                                    "size": "Medium",
                                    "color": "Good"
                                },
                                {
                                    "type": "TextBlock",
                                    "text": "Conexão com Webhook Configurada com Sucesso!",
                                    "spacing": "None"
                                }
                            ]
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Este é um disparo de teste para o canal '{channel.name}'.",
                            "wrap": True,
                            "spacing": "Medium"
                        }
                    ]
                }
            }
        ]
    }
    send_adaptive_card_to_teams(channel.webhook_url, card)
    return {"status": "tested", "message": "Mensagem de teste enviada com sucesso!"}

# --- Rotas de Envio Manual Individual de Relatório ---

@router.post("/send-report/{report_id}")
def send_report_to_teams(report_id: int, data: dict, request: Request, db: Session = Depends(get_db)):
    channel_id = data.get("channel_id")
    if not channel_id:
        raise HTTPException(422, detail="ID do canal do Teams é obrigatório.")
        
    report = db.query(ExecutionReport).filter(
        ExecutionReport.id == report_id,
        ExecutionReport.is_deleted == False
    ).first()
    if not report:
        raise HTTPException(404, detail="Relatório não encontrado.")
        
    channel = db.query(TeamsChannel).filter(
        TeamsChannel.id == channel_id,
        TeamsChannel.is_deleted == False
    ).first()
    if not channel:
        raise HTTPException(404, detail="Canal do Teams não encontrado.")
        
    # Construir URLs dinamicamente com base no request.base_url
    base_url = str(request.base_url)
    download_url = f"{base_url.rstrip('/')}/api/reports/{report.id}/download"
    
    # Formatação de dados
    generated_at_str = report.created_at.strftime("%d/%m/%Y %H:%M:%S") if report.created_at else "-"
    period_start_str = report.period_start.strftime("%d/%m/%Y") if report.period_start else ""
    period_end_str = report.period_end.strftime("%d/%m/%Y") if report.period_end else ""
    
    period_label = "Completo"
    if period_start_str and period_end_str:
        period_label = f"{period_start_str} até {period_end_str}"
    elif period_start_str:
        period_label = f"A partir de {period_start_str}"
    elif period_end_str:
        period_label = f"Até {period_end_str}"
        
    report_type = report.type.split("|")[0] if report.type else "Relatório"
    file_format = report.type.split("|")[1] if report.type and "|" in report.type else "xlsx"
    
    card = build_report_adaptive_card(
        report_name=report.name or f"Relatório #{report.id}",
        report_type=report_type,
        file_format=file_format,
        generated_at=generated_at_str,
        download_url=download_url,
        period_label=period_label
    )
    
    send_adaptive_card_to_teams(channel.webhook_url, card)
    create_log(
        db,
        "info",
        f"Relatório '{report.name}' enviado manualmente para Teams: {channel.name}",
        "report_teams_send",
        report.id,
        metadata={"channel_id": channel.id, "channel_name": channel.name}
    )
    return {"status": "sent", "message": f"Relatório enviado com sucesso para {channel.name}!"}

# --- Rotas de Agendamento de Relatórios ---

@router.get("/report-schedules")
def list_report_schedules(db: Session = Depends(get_db)):
    schedules = db.query(TeamsReportSchedule).filter(TeamsReportSchedule.is_deleted == False).order_by(TeamsReportSchedule.id.desc()).all()
    # Adicionar dados dos canais para o front-end
    result = []
    for s in schedules:
        channel = db.query(TeamsChannel).filter(TeamsChannel.id == s.channel_id).first()
        channel_name = channel.name if channel else f"Canal #{s.channel_id}"
        result.append({
            "id": s.id,
            "name": s.name,
            "report_type": s.report_type,
            "file_format": s.file_format,
            "channel_id": s.channel_id,
            "channel_name": channel_name,
            "frequency_type": s.frequency_type,
            "run_date": s.run_date,
            "time_of_day": s.time_of_day,
            "days_of_week": s.days_of_week,
            "day_of_month": s.day_of_month,
            "next_run_at": s.next_run_at,
            "last_run_at": s.last_run_at,
            "status": s.status,
            "created_at": s.created_at
        })
    return result

@router.post("/report-schedules")
def create_report_schedule(data: dict, db: Session = Depends(get_db)):
    name = str(data.get("name") or "").strip()
    report_type = str(data.get("report_type") or "Relatório Geral").strip()
    file_format = str(data.get("file_format") or "xlsx").strip()
    channel_id = data.get("channel_id")
    frequency_type = str(data.get("frequency_type") or "daily").strip()
    
    if not name or not channel_id or not frequency_type:
        raise HTTPException(422, detail="Nome, canal e frequência são campos obrigatórios.")
        
    # Validar canal
    channel = db.query(TeamsChannel).filter(TeamsChannel.id == channel_id, TeamsChannel.is_deleted == False).first()
    if not channel:
        raise HTTPException(422, detail="Canal do Teams selecionado é inválido.")
        
    run_date_val = None
    if frequency_type == "once" and data.get("run_date"):
        try:
            run_date_val = datetime.fromisoformat(str(data.get("run_date")).replace("Z", ""))
        except Exception:
            raise HTTPException(422, detail="Data de disparo única inválida.")

    schedule = TeamsReportSchedule(
        name=name,
        report_type=report_type,
        file_format=file_format,
        channel_id=channel_id,
        frequency_type=frequency_type,
        run_date=run_date_val,
        time_of_day=data.get("time_of_day"),
        days_of_week=json.dumps(data.get("days_of_week")) if data.get("days_of_week") else None,
        day_of_month=data.get("day_of_month"),
        status="active"
    )
    
    schedule.next_run_at = compute_report_next_run(schedule)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    create_log(db, "info", f"Agendamento de relatório criado: {name}", "report_schedule", schedule.id)
    return schedule

@router.put("/report-schedules/{id}")
def update_report_schedule(id: int, data: dict, db: Session = Depends(get_db)):
    schedule = db.query(TeamsReportSchedule).filter(TeamsReportSchedule.id == id, TeamsReportSchedule.is_deleted == False).first()
    if not schedule:
        raise HTTPException(404, detail="Agendamento não encontrado.")
        
    if "name" in data:
        schedule.name = str(data["name"]).strip()
    if "report_type" in data:
        schedule.report_type = str(data["report_type"]).strip()
    if "file_format" in data:
        schedule.file_format = str(data["file_format"]).strip()
    if "channel_id" in data:
        schedule.channel_id = data["channel_id"]
    if "frequency_type" in data:
        schedule.frequency_type = str(data["frequency_type"]).strip()
    if "time_of_day" in data:
        schedule.time_of_day = data["time_of_day"]
    if "day_of_month" in data:
        schedule.day_of_month = data["day_of_month"]
    if "days_of_week" in data:
        schedule.days_of_week = json.dumps(data["days_of_week"]) if data["days_of_week"] else None
    if "run_date" in data:
        if data["run_date"]:
            try:
                schedule.run_date = datetime.fromisoformat(str(data["run_date"]).replace("Z", ""))
            except Exception:
                raise HTTPException(422, detail="Data de disparo única inválida.")
        else:
            schedule.run_date = None
    if "status" in data:
        schedule.status = str(data["status"]).strip()
        
    schedule.next_run_at = compute_report_next_run(schedule)
    db.commit()
    db.refresh(schedule)
    create_log(db, "info", f"Agendamento de relatório atualizado: {schedule.name}", "report_schedule", schedule.id)
    return schedule

@router.delete("/report-schedules/{id}")
def delete_report_schedule(id: int, db: Session = Depends(get_db)):
    schedule = db.query(TeamsReportSchedule).filter(TeamsReportSchedule.id == id, TeamsReportSchedule.is_deleted == False).first()
    if not schedule:
        raise HTTPException(404, detail="Agendamento não encontrado.")
    schedule.is_deleted = True
    db.commit()
    create_log(db, "warning", f"Agendamento de relatório removido: {schedule.name}", "report_schedule", schedule.id)
    return {"status": "deleted"}
