from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.timezone import sao_paulo_utc_iso
from app.db.session import get_db
from app.models.agent import AgentTask
from app.models.automation import Automation
from app.models.execution import ExecutionReport
from app.models.file import WorkspaceFile
from app.models.integration import IntegrationConnection
from app.models.playground_user import WorkspaceExternalUser
from app.models.schedule import Schedule
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit import create_log

router = APIRouter()


# --- extratores de nome amigavel por entidade ---
def _name_file(item: Any) -> str:
    return item.file_name or f"arquivo #{item.id}"


def _name_execution(item: Any) -> str:
    return f"{item.task_type or 'execução'} #{item.id}"


def _name_integration(item: Any) -> str:
    return item.account_label or item.provider or f"integração #{item.id}"


# Registro central da Lixeira: tipo -> (Model, rotulo PT, extrator_de_nome).
# Todos os deletes do dashboard ja sao soft-delete (is_deleted=True); a Lixeira apenas expoe,
# restaura ou remove definitivamente esses registros. Extensivel: adicione uma linha aqui para
# incluir um novo tipo. So entram entidades com is_deleted/deleted_at.
TRASH_REGISTRY: dict[str, tuple[Any, str, Callable[[Any], str]]] = {
    "workspace": (Workspace, "Workspace", lambda x: x.name or f"workspace #{x.id}"),
    "automation": (Automation, "Automação", lambda x: x.name or f"automação #{x.id}"),
    "schedule": (Schedule, "Agendamento", lambda x: x.name or f"agendamento #{x.id}"),
    "report": (ExecutionReport, "Relatório", lambda x: x.name or f"relatório #{x.id}"),
    "external_user": (WorkspaceExternalUser, "Usuário externo", lambda x: x.name or x.email or f"usuário #{x.id}"),
    "file": (WorkspaceFile, "Arquivo", _name_file),
    "user": (User, "Usuário", lambda x: x.name or x.email or f"usuário #{x.id}"),
    "execution": (AgentTask, "Execução", _name_execution),
    "integration": (IntegrationConnection, "Integração", _name_integration),
}


def _registry_or_404(entity_type: str) -> tuple[Any, str, Callable[[Any], str]]:
    entry = TRASH_REGISTRY.get(entity_type)
    if not entry:
        raise HTTPException(404, detail=f"Tipo de item desconhecido na lixeira: {entity_type}")
    return entry


def _deleted_item_or_404(db: Session, entity_type: str, item_id: int):
    model, label, name_of = _registry_or_404(entity_type)
    item = (
        db.query(model)
        .filter(model.id == item_id, model.is_deleted == True)  # noqa: E712
        .first()
    )
    if item is None:
        raise HTTPException(404, detail="Item nao encontrado na lixeira (ja restaurado ou removido).")
    return model, label, name_of, item


def _serialize(entity_type: str, label: str, name_of: Callable[[Any], str], item: Any) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "label": label,
        "id": item.id,
        "name": name_of(item),
        "deleted_at": sao_paulo_utc_iso(getattr(item, "deleted_at", None)),
    }


def _purge_side_effects(db: Session, entity_type: str, item: Any) -> None:
    """Limpeza fisica e de integridade ao excluir DEFINITIVAMENTE (best-effort)."""
    import shutil
    if entity_type == "report":
        path = getattr(item, "file_path", None)
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
    elif entity_type == "file":
        # Apaga o arquivo temporario/fisico no disco
        temp_path = getattr(item, "temp_path", None)
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass
        pdf_path = getattr(item, "pdf_path", None)
        if pdf_path:
            try:
                Path(pdf_path).unlink(missing_ok=True)
            except OSError:
                pass
    elif entity_type == "automation":
        # Apaga a pasta temporaria de staging da automacao
        temp_folder = getattr(item, "temp_folder_path", None)
        if temp_folder:
            try:
                shutil.rmtree(temp_folder, ignore_errors=True)
            except Exception:
                pass
        # Apaga os agendamentos (Schedules) vinculados para evitar violacao de FK
        try:
            from app.models.schedule import Schedule
            schedules = db.query(Schedule).filter(Schedule.automation_id == item.id).all()
            for s in schedules:
                db.delete(s)
        except Exception:
            pass
    elif entity_type == "workspace":
        # Para evitar violacao de Foreign Key no SQLite, precisamos excluir
        # os arquivos e automacoes associados a este workspace.
        try:
            # 1. WorkspaceFiles vinculados
            from app.models.file import WorkspaceFile
            files = db.query(WorkspaceFile).filter(WorkspaceFile.workspace_id == item.id).all()
            for f in files:
                _purge_side_effects(db, "file", f)
                db.delete(f)
            
            # 2. Automations vinculadas
            from app.models.automation import Automation
            autos = db.query(Automation).filter(Automation.workspace_id == item.id).all()
            for a in autos:
                _purge_side_effects(db, "automation", a)
                db.delete(a)
        except Exception:
            pass


@router.get("")
def list_trash(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Lista TODOS os itens excluidos (soft-delete) de todas as entidades do dashboard."""
    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for entity_type, (model, label, name_of) in TRASH_REGISTRY.items():
        rows = (
            db.query(model)
            .filter(model.is_deleted == True)  # noqa: E712
            .order_by(model.deleted_at.desc(), model.id.desc())
            .all()
        )
        counts[entity_type] = len(rows)
        for row in rows:
            items.append(_serialize(entity_type, label, name_of, row))
    items.sort(key=lambda entry: entry["deleted_at"] or "", reverse=True)
    return {"items": items, "counts": counts, "total": len(items)}


@router.get("/summary")
def trash_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Contagem por tipo + total, sem serializar os itens (para o badge do card)."""
    counts: dict[str, int] = {}
    total = 0
    for entity_type, (model, _label, _name) in TRASH_REGISTRY.items():
        count = db.query(model).filter(model.is_deleted == True).count()  # noqa: E712
        counts[entity_type] = count
        total += count
    return {"counts": counts, "total": total}


@router.post("/{entity_type}/{item_id}/restore")
def restore_item(entity_type: str, item_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Restaura um item da lixeira (volta a ser funcional no dashboard)."""
    _model, label, name_of, item = _deleted_item_or_404(db, entity_type, item_id)
    name = name_of(item)
    item.is_deleted = False
    item.deleted_at = None
    if hasattr(item, "updated_at"):
        item.updated_at = datetime.utcnow()
    create_log(db, "info", f"Item restaurado da lixeira: {label} '{name}'", entity_type=entity_type, entity_id=item_id)
    return {"status": "restored", "entity_type": entity_type, "id": item_id, "name": name}


@router.delete("/{entity_type}/{item_id}")
def purge_item(entity_type: str, item_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Exclui DEFINITIVAMENTE um item da lixeira (remove a linha do banco)."""
    _model, label, name_of, item = _deleted_item_or_404(db, entity_type, item_id)
    name = name_of(item)
    _purge_side_effects(db, entity_type, item)
    db.delete(item)
    db.commit()
    create_log(db, "warning", f"Item excluido DEFINITIVAMENTE da lixeira: {label} '{name}'", entity_type=entity_type, entity_id=item_id)
    return {"status": "purged", "entity_type": entity_type, "id": item_id, "name": name}


@router.delete("")
def purge_all_trash(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Exclui DEFINITIVAMENTE todos os itens da lixeira (esvazia a lixeira)."""
    purged_counts: dict[str, int] = {}
    total_purged = 0
    for entity_type, (model, _label, _name_of) in TRASH_REGISTRY.items():
        items = (
            db.query(model)
            .filter(model.is_deleted == True)  # noqa: E712
            .all()
        )
        count = len(items)
        if count > 0:
            purged_counts[entity_type] = count
            total_purged += count
            for item in items:
                _purge_side_effects(db, entity_type, item)
                db.delete(item)
    if total_purged > 0:
        db.commit()
        create_log(
            db,
            "warning",
            f"Lixeira esvaziada: {total_purged} itens excluidos DEFINITIVAMENTE.",
            entity_type="trash",
            entity_id=0,
        )
    return {"status": "purged_all", "purged_counts": purged_counts, "total": total_purged}

