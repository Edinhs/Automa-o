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

from app.core.config import runtime_path, settings
from app.db.session import get_db
from app.models.automation import Automation
from app.models.execution import ExecutionLog, ExecutionReport
from app.models.file import WorkspaceFile
from app.models.workspace import Workspace
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
}
REPORT_TYPES = {
    "relatorio geral": ("Relatório Geral", ["files", "local_errors"]),
    "relatorio arquivos": ("Relatório Arquivos", ["files"]),
    "relatorio erros locais": ("Relatório Erros Locais", ["local_errors"]),
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
        raise HTTPException(422, detail="Tipo de relatorio invalido. Use apenas Geral, Arquivos ou Erros Locais.")
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
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


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


BLOCK_BUILDERS = {
    "files": block_files,
    "local_errors": block_local_errors,
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


def build_excel(report_type: str, file_format: str, filters: dict[str, Any], sections: list[ReportSection]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    used_names: set[str] = set()
    all_sections = [summary_section(report_type, file_format, filters, sections), *sections]
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(bold=True, color="FFFFFF")
    for index, section in enumerate(all_sections):
        ws = wb.active if index == 0 else wb.create_sheet()
        ws.title = safe_sheet_name(section.title, used_names)
        for col_idx, header in enumerate(section.headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        for row_idx, row in enumerate(section.rows, start=2):
            for col_idx, value in enumerate(row, start=1):
                ws.cell(row=row_idx, column=col_idx, value=normalize_cell(value))
        if not section.rows:
            ws.cell(row=2, column=1, value="Sem registros para os filtros selecionados.")
        for column in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in column), default=10)
            ws.column_dimensions[column[0].column_letter].width = min(max(max_len + 4, 12), 70)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pdf_table(section: ReportSection, styles):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    data_rows = section.rows or [["Sem registros para os filtros selecionados."] + [""] * (len(section.headers) - 1)]
    table_data = [
        [Paragraph(f"<b>{escape(str(header))}</b>", styles["BodyText"]) for header in section.headers],
        *[[Paragraph(escape(normalize_cell(value)), styles["BodyText"]) for value in row] for row in data_rows[:80]],
    ]
    col_width = 760 / max(len(section.headers), 1)
    table = Table(table_data, colWidths=[col_width] * len(section.headers), repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F8")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def build_pdf(report_type: str, file_format: str, filters: dict[str, Any], sections: list[ReportSection]) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=cm, rightMargin=cm, topMargin=cm, bottomMargin=cm)
    styles = getSampleStyleSheet()
    styles["BodyText"].fontSize = 6
    styles["BodyText"].leading = 7
    elements = [
        Paragraph("<b>Stellantis Automation HUB</b>", styles["Title"]),
        Paragraph(f"Relatorio: {escape(report_type)}", styles["Heading2"]),
        Spacer(1, 0.3 * cm),
        pdf_table(summary_section(report_type, file_format, filters, sections), styles),
        Spacer(1, 0.5 * cm),
    ]
    for index, section in enumerate(sections):
        if index:
            elements.append(PageBreak())
        elements.append(Paragraph(escape(section.title), styles["Heading2"]))
        elements.append(Spacer(1, 0.2 * cm))
        elements.append(pdf_table(section, styles))
        if len(section.rows) > 80:
            elements.append(Spacer(1, 0.2 * cm))
            elements.append(Paragraph(f"Exibindo 80 de {len(section.rows)} registros nesta secao.", styles["Normal"]))
    doc.build(elements)
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
