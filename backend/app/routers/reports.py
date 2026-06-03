import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, runtime_path, settings
from app.core.serialization import parse_json_object
from app.db.session import get_db
from app.models.automation import Automation
from app.models.execution import ExecutionLog, ExecutionReport
from app.models.file import WorkspaceFile
from app.models.workspace import Workspace
from app.models.agent import AgentTask
from app.models.schedule import Schedule
from app.routers.executions import (
    STATUS_FILTERS,
    STATUS_LABELS,
    files_for_task,
    file_status_counts,
    normalize_text,
)
from app.services.audit import create_log

router = APIRouter()

REPORT_SOURCE_SCOPE = "folder_monitoring_detection"
DETECTION_SOURCE = "folder_monitoring"
LOCAL_REPORT_EVENTS = {
    "folder_not_found",
    "folder_inaccessible",
    "folder_scan_failed",
    "file_signature_failed",
    "subfolder_inaccessible",
    "item_inaccessible",
    "copy_failed",
    "no_files_copied",
}
REPORT_BLOCKS = {
    "files": "Arquivos Detectados",
    "local_errors": "Erros Locais",
    "automations": "Automações",
    "updated_files": "Arquivos Atualizados",
    "workspaces": "Workspaces",
    "schedules": "Agendamentos",
    "executions": "Execuções",
}
REPORT_TYPES = {
    "relatorio geral": ("Relatório Geral", ["files", "local_errors", "automations", "updated_files", "workspaces", "schedules", "executions"]),
    "relatorio arquivos": ("Relatório Arquivos", ["files"]),
    "relatorio erros locais": ("Relatório Erros Locais", ["local_errors"]),
    "relatorio automacao": ("Relatório Automação", ["automations"]),
    "relatorio atualizados": ("Relatório Atualizados", ["updated_files"]),
    "relatorio workspace": ("Relatório Workspace", ["workspaces"]),
    "relatorio agendamento": ("Relatório Agendamento", ["schedules"]),
    "relatorio execucoes": ("Relatório Execuções", ["executions"]),
}
MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "csv": "text/csv; charset=utf-8",
}


@dataclass
class ReportSection:
    key: str
    title: str
    headers: list[str]
    rows: list[list[Any]]


def normalize_key(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().strip().split())


def parse_report_type(value: str | None) -> str:
    raw = value or "Relatório Geral"
    requested = raw.split("|", 1)[0].strip() or "Relatório Geral"
    report_definition = REPORT_TYPES.get(normalize_key(requested))
    if not report_definition:
        raise HTTPException(422, detail="Tipo de relatorio invalido. Use apenas Geral, Arquivos, Erros Locais, Automação, Atualizados, Workspace, Agendamento ou Execuções.")
    return report_definition[0]


def parse_file_format(value: str | None, fallback_type: str | None = None) -> str:
    raw = (value or "").strip().lower().lstrip(".")
    if raw:
        return "xlsx" if raw in {"excel", "xls"} else raw
    parts = (fallback_type or "").split("|")
    if len(parts) > 1:
        return parse_file_format(parts[-1])
    return "csv"


def parse_environment_mode(value: Any) -> str:
    normalized = normalize_key(str(value or ""))
    if normalized in {"developer", "desenvolvedor", "dev", "test", "teste"}:
        return "developer"
    return "operational"


def parse_dt(value: Any, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                parsed = datetime.combine(datetime.fromisoformat(raw).date(), time.max if end_of_day else time.min)
            else:
                parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if parsed.tzinfo:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def safe_int(value: Any) -> int | None:
    if value in [None, "", "Todos"]:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_dt(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M:%S") if value else ""


def parse_json(raw: str | None) -> dict[str, Any]:
    return parse_json_object(raw)


def within_period(value: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if not value:
        return True
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True


def filters_from_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "start": parse_dt(data.get("date_start"), end_of_day=False),
        "end": parse_dt(data.get("date_end"), end_of_day=True),
        "automation_id": safe_int(data.get("automation_id")),
        "workspace_id": safe_int(data.get("workspace_id")),
        "status": None if data.get("status") in [None, "", "Todos"] else str(data.get("status")),
        "source_task_id": safe_int(data.get("source_task_id")),
    }


def sections_for_type(report_type: str) -> list[str]:
    return REPORT_TYPES[normalize_key(parse_report_type(report_type))][1]


def clean_filename(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "relatorio")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
    return text.lower() or "relatorio"


def report_filename(report_type: str, file_format: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return f"{clean_filename(report_type)}_{timestamp}.{file_format}"


def lookup_maps(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    automations = {
        item.id: item.name
        for item in db.query(Automation).filter(Automation.is_deleted == False, Automation.type == DETECTION_SOURCE).all()
    }
    workspaces = {
        item.id: item.name
        for item in db.query(Workspace).filter(Workspace.is_deleted == False).all()
    }
    return automations, workspaces


def reportable_automation_ids(db: Session) -> set[int]:
    return {
        item.id
        for item in db.query(Automation).filter(Automation.is_deleted == False, Automation.type == DETECTION_SOURCE).all()
    }


def block_files(db: Session, filters: dict[str, Any], names: tuple[dict[int, str], dict[int, str]]) -> ReportSection:
    automation_names, workspace_names = names
    permitted_automations = reportable_automation_ids(db)
    query = db.query(WorkspaceFile).filter(
        WorkspaceFile.is_deleted == False,
        WorkspaceFile.detection_source == DETECTION_SOURCE,
        WorkspaceFile.detection_task_id.isnot(None),
    )
    if filters["source_task_id"]:
        query = query.filter(WorkspaceFile.detection_task_id == filters["source_task_id"])
    rows = []
    for item in query.order_by(WorkspaceFile.detected_at.desc(), WorkspaceFile.id.desc()).all():
        if item.automation_id not in permitted_automations:
            continue
        if item.detection_classification not in {"new", "updated", "audit_duplicate"}:
            continue
        if filters["automation_id"] and item.automation_id != filters["automation_id"]:
            continue
        if filters["workspace_id"] and item.workspace_id != filters["workspace_id"]:
            continue
        if filters["status"] and item.detection_classification.lower() != filters["status"].lower():
            continue
        event_date = item.detected_at or item.created_at
        if not within_period(event_date, filters["start"], filters["end"]):
            continue
        rows.append([
            item.id,
            item.file_name or "",
            automation_names.get(item.automation_id, item.automation_id or ""),
            workspace_names.get(item.workspace_id, item.workspace_id or ""),
            item.detection_classification,
            item.extension or "",
            item.size_bytes or "",
            item.original_path or "",
            format_dt(event_date),
            item.detection_task_id,
        ])
    return ReportSection(
        "files",
        REPORT_BLOCKS["files"],
        ["ID", "Nome", "Automacao", "Workspace", "Classificacao", "Extensao", "Tamanho", "Caminho original", "Detectado em", "Ciclo"],
        rows,
    )


def block_local_errors(db: Session, filters: dict[str, Any], names: tuple[dict[int, str], dict[int, str]]) -> ReportSection:
    automation_names, _ = names
    permitted_automations = reportable_automation_ids(db)
    query = db.query(ExecutionLog).filter(ExecutionLog.level == "error")
    if filters["source_task_id"]:
        query = query.filter(ExecutionLog.task_id == filters["source_task_id"])
    rows = []
    for log in query.order_by(ExecutionLog.created_at.desc(), ExecutionLog.id.desc()).all():
        metadata = parse_json(log.metadata_json)
        if metadata.get("report_source") != REPORT_SOURCE_SCOPE:
            continue
        event = metadata.get("report_event")
        if event not in LOCAL_REPORT_EVENTS:
            continue
        if log.automation_id not in permitted_automations:
            continue
        if filters["automation_id"] and log.automation_id != filters["automation_id"]:
            continue
        if not within_period(log.created_at, filters["start"], filters["end"]):
            continue
        rows.append([
            log.id,
            event,
            automation_names.get(log.automation_id, log.automation_id or ""),
            log.task_id or "",
            log.message or "",
            format_dt(log.created_at),
            json.dumps({key: value for key, value in metadata.items() if key not in {"report_source", "report_event"}}, ensure_ascii=False),
        ])
    return ReportSection(
        "local_errors",
        REPORT_BLOCKS["local_errors"],
        ["ID", "Evento", "Automacao", "Ciclo", "Mensagem", "Data", "Detalhes"],
        rows,
    )


def block_automations(db: Session, filters: dict[str, Any], names: tuple[dict[int, str], dict[int, str]]) -> ReportSection:
    _, workspace_names = names
    query = db.query(Automation).filter(Automation.is_deleted == False)
    if filters["automation_id"]:
        query = query.filter(Automation.id == filters["automation_id"])
    rows = []
    for item in query.order_by(Automation.id.desc()).all():
        if not within_period(item.created_at, filters["start"], filters["end"]):
            continue
        rows.append([
            item.id,
            item.name or "",
            item.description or "",
            item.type or "",
            item.status or "",
            item.folder_path or "",
            item.temp_folder_path or "",
            format_dt(item.created_at),
        ])
    return ReportSection("automations", REPORT_BLOCKS["automations"], ["ID", "Nome", "Descrição", "Tipo", "Status", "Pasta Monitorada", "Pasta Temporária", "Criada em"], rows)


def block_updated_files(db: Session, filters: dict[str, Any], names: tuple[dict[int, str], dict[int, str]]) -> ReportSection:
    automation_names, workspace_names = names
    permitted_automations = reportable_automation_ids(db)
    query = db.query(WorkspaceFile).filter(
        WorkspaceFile.is_deleted == False,
        WorkspaceFile.detection_source == DETECTION_SOURCE,
        WorkspaceFile.detection_task_id.isnot(None),
        WorkspaceFile.detection_classification == "updated",
    )
    if filters["source_task_id"]:
        query = query.filter(WorkspaceFile.detection_task_id == filters["source_task_id"])
    rows = []
    for item in query.order_by(WorkspaceFile.detected_at.desc(), WorkspaceFile.id.desc()).all():
        if item.automation_id not in permitted_automations:
            continue
        if filters["automation_id"] and item.automation_id != filters["automation_id"]:
            continue
        if filters["workspace_id"] and item.workspace_id != filters["workspace_id"]:
            continue
        event_date = item.detected_at or item.created_at
        if not within_period(event_date, filters["start"], filters["end"]):
            continue
        rows.append([
            item.id,
            item.file_name or "",
            automation_names.get(item.automation_id, item.automation_id or ""),
            workspace_names.get(item.workspace_id, item.workspace_id or ""),
            item.detection_classification,
            item.extension or "",
            item.size_bytes or "",
            item.original_path or "",
            format_dt(event_date),
            item.detection_task_id,
        ])
    return ReportSection("updated_files", REPORT_BLOCKS["updated_files"], ["ID", "Nome", "Automação", "Workspace", "Classificação", "Extensão", "Tamanho", "Caminho original", "Detectado em", "Ciclo"], rows)


def block_workspaces(db: Session, filters: dict[str, Any], names: tuple[dict[int, str], dict[int, str]]) -> ReportSection:
    query = db.query(Workspace).filter(Workspace.is_deleted == False)
    if filters["workspace_id"]:
        query = query.filter(Workspace.id == filters["workspace_id"])
    rows = []
    for item in query.order_by(Workspace.id.desc()).all():
        if not within_period(item.created_at, filters["start"], filters["end"]):
            continue
        rows.append([
            item.id,
            item.name or "",
            item.description or "",
            item.playground_workspace_id or "",
            item.playground_url or "",
            item.embedding_model or "",
            item.data_languages or "",
            item.status or "",
            item.created_via or "",
            format_dt(item.created_at),
        ])
    return ReportSection("workspaces", REPORT_BLOCKS["workspaces"], ["ID", "Nome", "Descrição", "Playground ID", "Playground URL", "Embedding Model", "Data Languages", "Status", "Criado Via", "Criado em"], rows)


def block_schedules(db: Session, filters: dict[str, Any], names: tuple[dict[int, str], dict[int, str]]) -> ReportSection:
    automation_names, _ = names
    query = db.query(Schedule).filter(Schedule.is_deleted == False)
    if filters["automation_id"]:
        query = query.filter(Schedule.automation_id == filters["automation_id"])
    rows = []
    for item in query.order_by(Schedule.id.desc()).all():
        if not within_period(item.created_at, filters["start"], filters["end"]):
            continue
        rows.append([
            item.id,
            item.name or "",
            automation_names.get(item.automation_id, item.automation_id or ""),
            item.frequency_type or "",
            item.time_of_day or "",
            item.days_of_week or "",
            item.day_of_month or "",
            format_dt(item.next_run_at),
            format_dt(item.last_run_at),
            item.status or "",
            format_dt(item.created_at),
        ])
    return ReportSection("schedules", REPORT_BLOCKS["schedules"], ["ID", "Nome", "Automação", "Frequência", "Hora", "Dias da Semana", "Dia do Mês", "Próxima Execução", "Última Execução", "Status", "Criado em"], rows)


def block_executions(db: Session, filters: dict[str, Any], names: tuple[dict[int, str], dict[int, str]]) -> ReportSection:
    automation_names, workspace_names = names
    query = db.query(AgentTask).filter(
        AgentTask.is_deleted == False,
        AgentTask.started_at.isnot(None),
    )
    if filters["source_task_id"]:
        query = query.filter(AgentTask.id == filters["source_task_id"])
    rows = []
    for task in query.order_by(AgentTask.started_at.desc(), AgentTask.id.desc()).all():
        payload = parse_json(task.payload_json)
        automation_id = payload.get("automation_id")
        workspace_id = payload.get("workspace_id")
        
        if filters["automation_id"] and automation_id != filters["automation_id"]:
            continue
        if filters["workspace_id"] and workspace_id != filters["workspace_id"]:
            continue
        if not within_period(task.started_at, filters["start"], filters["end"]):
            continue
        
        files = files_for_task(db, task, payload)
        counts = file_status_counts(files)
        
        status_label = STATUS_LABELS.get(task.status or "", task.status or "Pendente")
        if filters["status"] and task.status != STATUS_FILTERS.get(normalize_text(filters["status"]), filters["status"]):
            continue
            
        end = task.completed_at or task.failed_at or datetime.utcnow()
        duration = max(int((end - task.started_at).total_seconds()), 0) if task.started_at else 0
        
        rows.append([
            task.id,
            task.task_type or "",
            automation_names.get(automation_id, automation_id or ""),
            workspace_names.get(workspace_id, workspace_id or payload.get("workspace_name") or ""),
            format_dt(task.started_at),
            format_dt(task.completed_at or task.failed_at),
            duration,
            counts["total"],
            counts["success"],
            counts["errors"],
            status_label,
        ])
    return ReportSection(
        "executions",
        REPORT_BLOCKS["executions"],
        ["ID", "Tipo de Tarefa", "Automação", "Workspace", "Início", "Fim", "Duração (s)", "Total de Arquivos", "Sucessos", "Erros", "Status"],
        rows,
    )


BLOCK_BUILDERS = {
    "files": block_files,
    "local_errors": block_local_errors,
    "automations": block_automations,
    "updated_files": block_updated_files,
    "workspaces": block_workspaces,
    "schedules": block_schedules,
    "executions": block_executions,
}


def build_sections(db: Session, report_type: str, filters: dict[str, Any]) -> list[ReportSection]:
    names = lookup_maps(db)
    return [BLOCK_BUILDERS[key](db, filters, names) for key in sections_for_type(report_type)]


def summary_section(report_type: str, file_format: str, filters: dict[str, Any], sections: list[ReportSection]) -> ReportSection:
    rows = [
        ["Tipo", report_type],
        ["Formato", file_format.upper()],
        ["Fonte exclusiva", "Monitoramento local da pasta antes da automacao WEB"],
        ["Data inicial", format_dt(filters["start"])],
        ["Data final", format_dt(filters["end"])],
        ["Automacao", filters["automation_id"] or "Todos"],
        ["Workspace", filters["workspace_id"] or "Todos"],
        ["Classificacao", filters["status"] or "Todos"],
        ["Ciclo", filters["source_task_id"] or "Todos"],
        ["Gerado em", format_dt(datetime.utcnow())],
    ]
    rows.extend([[section.title, len(section.rows)] for section in sections])
    return ReportSection("summary", "Resumo", ["Campo", "Valor"], rows)


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return format_dt(value)
    return str(value)


def safe_sheet_name(value: str, used: set[str]) -> str:
    base = re.sub(r"[:\\/?*\[\]]+", " ", value).strip()[:31] or "Aba"
    name = base
    index = 2
    while name in used:
        suffix = f" {index}"
        name = f"{base[:31 - len(suffix)]}{suffix}"
        index += 1
    used.add(name)
    return name


# ---- Identidade visual Stellantis (template corporativo dos relatórios) ----
BRAND_NAVY = "#26337E"
BRAND_NAVY_DARK = "#1C2657"
ROW_ALT = "#F2F4FA"
TEXT_DARK = "#1A1A1A"
TEXT_MUTED = "#6B7280"
GRID_COLOR = "#D5DAE8"
OK_GREEN = "#1E7B4F"
WARN_AMBER = "#B26A00"
ERR_RED = "#B42318"
# Colunas estreitas (não distribuem largura como as de texto) — usado no layout do PDF.
NARROW_HEADERS = {"ID", "Ciclo", "Extensão", "Tamanho", "Duração (s)", "Total de Arquivos", "Sucessos", "Erros", "Status", "Hora", "Dia do Mês"}
# Colunas longas que ganham quebra de texto no XLSX.
WRAP_HEADERS = {"Nome", "Mensagem", "Caminho original", "Playground URL", "Descrição", "Pasta Monitorada", "Pasta Temporária", "Detalhes", "Próxima Execução", "Última Execução"}


def stellantis_logo_path() -> Path | None:
    """Logo Stellantis para o cabeçalho dos relatórios; dist/ (release) → public/ (fonte)."""
    for rel in ("dist/assets/stellantis_logo.png", "public/assets/stellantis_logo.png"):
        candidate = BACKEND_DIR.parent / rel
        if candidate.exists():
            return candidate
    return None


def period_label(filters: dict[str, Any]) -> str:
    start = format_dt(filters.get("start")) or "—"
    end = format_dt(filters.get("end")) or "—"
    return f"Período: {start} a {end}"


def status_color(value: Any) -> str | None:
    v = str(value).strip().lower()
    if v in {"concluída", "concluida", "completed", "ready", "active", "sucesso"}:
        return OK_GREEN
    if v in {"em andamento", "running", "pending", "processing", "manual_review", "pendente", "aguardando"}:
        return WARN_AMBER
    if v in {"failed", "erro", "error", "falha", "cancelled", "cancelada"}:
        return ERR_RED
    return None


def build_excel(report_type: str, file_format: str, filters: dict[str, Any], sections: list[ReportSection]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    hx = lambda c: c.lstrip("#")
    navy = PatternFill("solid", fgColor=hx(BRAND_NAVY))
    navy_dark = PatternFill("solid", fgColor=hx(BRAND_NAVY_DARK))
    alt = PatternFill("solid", fgColor=hx(ROW_ALT))
    white_hdr = Font(bold=True, color="FFFFFF", size=10)
    white_title = Font(bold=True, color="FFFFFF", size=15)
    white_sub = Font(color="C9CFEA", size=9)
    sec_band = Font(bold=True, color="FFFFFF", size=12)
    thin = Side(style="thin", color=hx(GRID_COLOR))
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    generated = format_dt(datetime.utcnow())
    period = period_label(filters)
    logo_path = stellantis_logo_path()
    summary = summary_section(report_type, file_format, filters, sections)
    used_names: set[str] = set()
    wb = Workbook()

    def resumo_header(ws, span: int) -> None:
        """Logo no topo (fundo branco) + faixa navy de título — layout aprovado pelo usuário."""
        last = get_column_letter(max(span, 8))
        ws.row_dimensions[1].height = 18
        ws.row_dimensions[2].height = 22
        if logo_path is not None:
            img = XLImage(str(logo_path))
            aspect = (img.width / img.height) if img.height else 4.717
            img.height = 40
            img.width = int(40 * aspect)
            img.anchor = "A1"
            ws.add_image(img)
        ws.merge_cells(f"A3:{last}3")
        t = ws["A3"]
        t.value = f"Automation HUB  —  {report_type}"
        t.fill = navy
        t.font = white_title
        t.alignment = Alignment(horizontal="right", vertical="center")
        ws.row_dimensions[3].height = 24
        ws.merge_cells(f"A4:{last}4")
        s = ws["A4"]
        s.value = f"{period}    •    Gerado em: {generated}    •    Stellantis — Confidencial"
        s.fill = navy
        s.font = white_sub
        s.alignment = Alignment(horizontal="right", vertical="center")
        ws.row_dimensions[4].height = 14

    def write_section(ws, section: ReportSection, band_label: str, start_row: int, summary_mode: bool = False) -> None:
        ncols = max(len(section.headers), 1)
        last = get_column_letter(ncols)
        ws.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=ncols)
        band = ws.cell(row=start_row, column=1, value=band_label)
        band.fill = navy_dark
        band.font = sec_band
        band.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[start_row].height = 22
        hrow = start_row + 1
        for c, header in enumerate(section.headers, start=1):
            cell = ws.cell(row=hrow, column=c, value=header)
            cell.fill = navy
            cell.font = white_hdr
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center")
        rows = section.rows or [["Sem registros para os filtros selecionados."]]
        status_idx = section.headers.index("Status") + 1 if "Status" in section.headers else None
        for ri, row in enumerate(rows, start=hrow + 1):
            for ci, value in enumerate(row, start=1):
                cell = ws.cell(row=ri, column=ci, value=normalize_cell(value))
                cell.border = border
                header = section.headers[ci - 1] if ci - 1 < len(section.headers) else ""
                cell.alignment = Alignment(vertical="center", wrap_text=header in WRAP_HEADERS)
                if (ri - hrow) % 2 == 0:
                    cell.fill = alt
                if status_idx and ci == status_idx:
                    col = status_color(value)
                    if col:
                        cell.font = Font(bold=True, color=hx(col))
        ws.auto_filter.ref = f"A{hrow}:{last}{hrow + len(rows)}"
        if not summary_mode:
            ws.freeze_panes = ws.cell(row=hrow + 1, column=1)
        for col in range(1, ncols + 1):
            letter = get_column_letter(col)
            header = section.headers[col - 1] if col - 1 < len(section.headers) else ""
            values = [normalize_cell(r[col - 1]) if col - 1 < len(r) else "" for r in rows]
            maxlen = max([len(header)] + [len(v) for v in values], default=12)
            if header in WRAP_HEADERS:
                ws.column_dimensions[letter].width = min(max(maxlen, 18), 42)
            else:
                ws.column_dimensions[letter].width = min(max(maxlen + 3, 10), 32)

    # Aba Resumo (com logo + faixa de título)
    ws = wb.active
    ws.title = safe_sheet_name(summary.title, used_names)
    resumo_header(ws, len(summary.headers))
    write_section(ws, summary, "RESUMO", start_row=6, summary_mode=True)
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 56
    ws.sheet_view.showGridLines = False

    # Uma aba por relatório (seção), com faixa de título no topo
    for section in sections:
        ws = wb.create_sheet(safe_sheet_name(section.title, used_names))
        write_section(ws, section, section.title.upper(), start_row=1)
        ws.sheet_view.showGridLines = False

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_pdf(report_type: str, file_format: str, filters: dict[str, Any], sections: list[ReportSection]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as canvas_mod
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    page_w, page_h = landscape(A4)
    left = right = 1.1 * cm
    header_h = 1.9 * cm
    footer_h = 1.0 * cm
    usable = page_w - left - right
    generated = format_dt(datetime.utcnow())
    period = period_label(filters)
    logo_path = stellantis_logo_path()
    logo_reader = ImageReader(str(logo_path)) if logo_path else None
    if logo_reader is not None:
        lw, lh = logo_reader.getSize()
        aspect = (lw / lh) if lh else 4.717
    else:
        aspect = 4.717
    logo_h = 0.85 * cm
    logo_w = logo_h * aspect

    styles = getSampleStyleSheet()
    body = ParagraphStyle("rpt_body", parent=styles["BodyText"], fontSize=6.5, leading=8, textColor=colors.HexColor(TEXT_DARK))
    head_cell = ParagraphStyle("rpt_hc", parent=body, textColor=colors.white, fontName="Helvetica-Bold")
    sec_title = ParagraphStyle("rpt_st", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor(BRAND_NAVY), spaceBefore=2, spaceAfter=5)

    def draw_chrome(c, total_pages: int) -> None:
        band_y = page_h - header_h
        c.setFillColor(colors.HexColor(BRAND_NAVY))
        c.rect(0, band_y, page_w, header_h, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#3A47A0"))
        c.rect(0, band_y - 3, page_w, 3, fill=1, stroke=0)
        if logo_reader is not None:
            pad = 4
            c.setFillColor(colors.white)
            c.roundRect(left - pad, band_y + (header_h - logo_h) / 2 - pad, logo_w + 2 * pad, logo_h + 2 * pad, 4, fill=1, stroke=0)
            c.drawImage(logo_reader, left, band_y + (header_h - logo_h) / 2, width=logo_w, height=logo_h, mask="auto")
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 14)
        c.drawRightString(page_w - right, band_y + header_h - 17, "Automation HUB")
        c.setFont("Helvetica", 10)
        c.drawRightString(page_w - right, band_y + header_h - 31, report_type)
        c.setFillColor(colors.HexColor("#C9CFEA"))
        c.setFont("Helvetica", 7.5)
        c.drawRightString(page_w - right, band_y + 8, f"{period}   •   Gerado em: {generated}")
        c.setStrokeColor(colors.HexColor(GRID_COLOR))
        c.setLineWidth(0.5)
        c.line(left, footer_h, page_w - right, footer_h)
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor(TEXT_MUTED))
        c.drawString(left, footer_h - 11, "Stellantis — Confidencial · uso interno")
        c.drawCentredString(page_w / 2, footer_h - 11, "Automation HUB")
        c.drawRightString(page_w - right, footer_h - 11, f"pág {c.getPageNumber()}/{total_pages}")

    class NumberedCanvas(canvas_mod.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_states: list[dict] = []

        def showPage(self):
            self._saved_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_states)
            for state in self._saved_states:
                self.__dict__.update(state)
                draw_chrome(self, total)
                super().showPage()
            super().save()

    def col_widths(headers: list[str], summary_mode: bool) -> list[float]:
        if summary_mode:
            return [4.5 * cm, usable - 4.5 * cm]
        fixed = {h: (0.9 * cm if h == "ID" else 1.5 * cm) for h in headers if h in NARROW_HEADERS}
        flex = [h for h in headers if h not in fixed]
        each = (usable - sum(fixed.values())) / len(flex) if flex else 0
        return [fixed.get(h, each) for h in headers]

    def styled_table(section: ReportSection, summary_mode: bool = False) -> Table:
        data = [[Paragraph(escape(str(h)), head_cell) for h in section.headers]]
        rows = section.rows or [["Sem registros para os filtros selecionados."] + [""] * (len(section.headers) - 1)]
        status_idx = section.headers.index("Status") if "Status" in section.headers else None
        for ri, row in enumerate(rows[:80], start=1):
            cells = []
            for ci, value in enumerate(row):
                st = ParagraphStyle(f"c{ri}_{ci}", parent=body)
                if status_idx is not None and ci == status_idx:
                    col = status_color(value)
                    if col:
                        st.textColor = colors.HexColor(col)
                        st.fontName = "Helvetica-Bold"
                cells.append(Paragraph(escape(normalize_cell(value)), st))
            data.append(cells)
        table = Table(data, colWidths=col_widths(section.headers, summary_mode), repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND_NAVY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 6.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(ROW_ALT)]),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(BRAND_NAVY_DARK)),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(GRID_COLOR)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ]
        if summary_mode:
            style += [
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 1), (0, -1), colors.HexColor(BRAND_NAVY)),
            ]
        table.setStyle(TableStyle(style))
        return table

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=left, rightMargin=right,
        topMargin=header_h + 0.35 * cm, bottomMargin=footer_h + 0.35 * cm,
    )
    summary = summary_section(report_type, file_format, filters, sections)
    elements: list[Any] = [KeepTogether([Paragraph(escape(summary.title), sec_title), styled_table(summary, summary_mode=True)]), Spacer(1, 0.4 * cm)]
    for section in sections:
        note = []
        if len(section.rows) > 80:
            note = [Paragraph(f"Exibindo 80 de {len(section.rows)} registros nesta seção.", body)]
        elements.append(KeepTogether([Paragraph(escape(section.title), sec_title), styled_table(section), *note]))
        elements.append(Spacer(1, 0.45 * cm))
    doc.build(elements, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def build_csv(report_type: str, file_format: str, filters: dict[str, Any], sections: list[ReportSection]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    if normalize_key(report_type) == "relatorio geral":
        for section in [summary_section(report_type, file_format, filters, sections), *sections]:
            writer.writerow([section.title])
            writer.writerow(section.headers)
            writer.writerows(section.rows)
            writer.writerow([])
    else:
        section = sections[0]
        writer.writerow(section.headers)
        writer.writerows(section.rows)
    return buf.getvalue()


def build_report_content(report_type: str, file_format: str, filters: dict[str, Any], db: Session) -> bytes:
    sections = build_sections(db, report_type, filters)
    if file_format == "xlsx":
        return build_excel(report_type, file_format, filters, sections)
    if file_format == "pdf":
        return build_pdf(report_type, file_format, filters, sections)
    return build_csv(report_type, file_format, filters, sections).encode("utf-8-sig")


def write_report_file(report_type: str, file_format: str, filters: dict[str, Any], db: Session) -> Path:
    reports_dir = runtime_path("REPORTS_PATH")
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / report_filename(report_type, file_format)
    path.write_bytes(build_report_content(report_type, file_format, filters, db))
    return path


def report_type_and_format(rep: ExecutionReport) -> tuple[str, str]:
    report_type = parse_report_type(rep.type)
    return report_type, parse_file_format(None, rep.type)


def report_out(rep: ExecutionReport) -> dict[str, Any]:
    report_type, file_format = report_type_and_format(rep)
    return {
        "id": rep.id,
        "name": rep.name,
        "file_name": Path(rep.file_path).name if rep.file_path else rep.name,
        "report_type": report_type,
        "type": rep.type,
        "file_format": file_format,
        "file_path": rep.file_path,
        "status": rep.status,
        "source_scope": rep.source_scope,
        "generation_trigger": rep.generation_trigger,
        "source_task_id": rep.source_task_id,
        "period_start": rep.period_start,
        "period_end": rep.period_end,
        "generated_by_id": rep.generated_by_id,
        "generated_at": rep.created_at,
        "created_at": rep.created_at,
        "updated_at": rep.updated_at,
    }


def persist_report(
    db: Session,
    report_type: str,
    file_format: str,
    filters: dict[str, Any],
    generated_by_id: int | None,
    generation_trigger: str,
    source_task_id: int | None,
) -> ExecutionReport:
    path = write_report_file(report_type, file_format, filters, db)
    report = ExecutionReport(
        name=f"{report_type} ({file_format.upper()})",
        type=f"{report_type}|{file_format}",
        status="ready",
        file_path=str(path),
        source_scope=REPORT_SOURCE_SCOPE,
        generation_trigger=generation_trigger,
        source_task_id=source_task_id,
        period_start=filters["start"],
        period_end=filters["end"],
        generated_by_id=generated_by_id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    create_log(
        db,
        "info",
        f"Report created: {report.name}",
        "report",
        report.id,
        metadata={"source_scope": REPORT_SOURCE_SCOPE, "generation_trigger": generation_trigger, "source_task_id": source_task_id},
    )
    return report


def create_automatic_folder_monitoring_report(db: Session, data: dict[str, Any]) -> dict[str, Any]:
    source_task_id = safe_int(data.get("source_task_id"))
    if not source_task_id:
        raise HTTPException(422, detail="source_task_id obrigatorio para relatorio automatico.")
    existing = db.query(ExecutionReport).filter(
        ExecutionReport.is_deleted == False,
        ExecutionReport.source_scope == REPORT_SOURCE_SCOPE,
        ExecutionReport.generation_trigger == "automatic",
        ExecutionReport.source_task_id == source_task_id,
    ).first()
    if existing:
        return {"report": report_out(existing), "saved": True, "created": False, "environment_mode": "operational"}
    filters = filters_from_payload({**data, "source_task_id": source_task_id})
    sections = build_sections(db, "Relatório Geral", filters)
    if not any(section.rows for section in sections):
        return {
            "report": None,
            "saved": False,
            "created": False,
            "skipped": True,
            "environment_mode": "operational",
        }
    report = persist_report(
        db,
        "Relatório Geral",
        "xlsx",
        filters,
        safe_int(data.get("generated_by_id")),
        "automatic",
        source_task_id,
    )
    return {"report": report_out(report), "saved": True, "created": True, "environment_mode": "operational"}


def fallback_content(rep: ExecutionReport, file_format: str, db: Session) -> bytes:
    report_type, _ = report_type_and_format(rep)
    filters = {
        "start": rep.period_start,
        "end": rep.period_end,
        "automation_id": None,
        "workspace_id": None,
        "status": None,
        "source_task_id": rep.source_task_id if rep.generation_trigger == "automatic" else None,
    }
    return build_report_content(report_type, file_format, filters, db)


@router.get("")
def list_reports(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    reports = (
        db.query(ExecutionReport)
        .filter(ExecutionReport.is_deleted == False, ExecutionReport.source_scope == REPORT_SOURCE_SCOPE)
        .order_by(ExecutionReport.created_at.desc(), ExecutionReport.id.desc())
        .limit(limit)
        .all()
    )
    return [report_out(report) for report in reports]


@router.post("")
def create_report(data: dict, db: Session = Depends(get_db)):
    report_type = parse_report_type(data.get("report_type"))
    file_format = parse_file_format(data.get("file_format"))
    if file_format not in MEDIA_TYPES:
        raise HTTPException(422, detail="Formato de relatorio invalido.")
    filters = filters_from_payload(data)
    environment_mode = parse_environment_mode(data.get("environment_mode") or data.get("app_mode"))
    if environment_mode == "developer":
        build_report_content(report_type, file_format, filters, db)
        return {
            "report": None,
            "saved": False,
            "environment_mode": "developer",
            "message": "Modo Desenvolvedor: relatorio processado para teste e nada foi salvo.",
        }
    report = persist_report(
        db,
        report_type,
        file_format,
        filters,
        safe_int(data.get("generated_by_id") or data.get("generated_by_user_id")),
        "manual",
        None,
    )
    return {"report": report_out(report), "saved": True, "environment_mode": "operational"}


@router.get("/{id}/download")
def download_report(id: int, db: Session = Depends(get_db)):
    report = db.query(ExecutionReport).filter(
        ExecutionReport.id == id,
        ExecutionReport.is_deleted == False,
        ExecutionReport.source_scope == REPORT_SOURCE_SCOPE,
    ).first()
    if not report:
        raise HTTPException(404, detail="Relatorio nao encontrado.")
    _, file_format = report_type_and_format(report)
    safe_name = Path(report.file_path).name if report.file_path else f"{clean_filename(report.name or f'report_{report.id}')}.{file_format}"
    media_type = MEDIA_TYPES.get(file_format, MEDIA_TYPES["csv"])
    if report.file_path and Path(report.file_path).exists():
        create_log(db, "info", "Downloaded report", "report", report.id, metadata={"source_scope": REPORT_SOURCE_SCOPE})
        return FileResponse(report.file_path, media_type=media_type, filename=safe_name)
    content = fallback_content(report, file_format, db)
    create_log(db, "info", "Downloaded report", "report", report.id, metadata={"source_scope": REPORT_SOURCE_SCOPE})
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.delete("/{id}")
def delete_report(id: int, db: Session = Depends(get_db)):
    report = db.query(ExecutionReport).filter(
        ExecutionReport.id == id,
        ExecutionReport.is_deleted == False,
        ExecutionReport.source_scope == REPORT_SOURCE_SCOPE,
    ).first()
    if not report:
        raise HTTPException(404, detail="Report not found")
    report.is_deleted = True
    report.deleted_at = datetime.utcnow()
    db.commit()
    create_log(db, "warning", f"Report marked as deleted: {report.name}", "report", report.id)
    return {"status": "deleted"}
