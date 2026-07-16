"""Overview — agregacoes do Home computadas no servidor (contagens exatas).

Motivacao: o dashboard montava os cards do Home somando os arrays de arquivos e
execucoes carregados no navegador. Esses arrays vem paginados (limite maximo de
1000 linhas), entao acima disso os cards subcontavam. Este endpoint devolve as
contagens direto do banco (COUNT), sem limite e com payload O(1).

Segue o isolamento dual-environment: `get_db()` resolve o engine do ambiente
corrente (ContextVar setado pelo middleware a partir de `X-App-Environment`), o
mesmo header que o dashboard ja envia. Nao importa nada de fora de `app`.

Nomes de campo espelham as chaves que o Home ja consome (`processedFiles`,
`errorFiles`, `errorsResolved`) para o front poder sobrescrever direto.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.automation import Automation
from app.models.file import WorkspaceFile
from app.models.workspace import Workspace

router = APIRouter()

# Mesma convencao ja usada no backend (ex.: errors_count por workspace).
_ERROR_STATUSES = ("error", "failed")
_READY_STATUSES = ("ready",)
_RESOLVED_STATUSES = ("resolved",)
_MANUAL_STATUSES = ("manual_review",)


def _playground_error_criteria():
    """Espelha o predicado `Ka` do front: playground_status contendo 'erro'/'error'
    (case-insensitive). Um valor NULL nao casa (lower(NULL) -> NULL)."""
    col = func.lower(WorkspaceFile.playground_status)
    return or_(col.like("%erro%"), col.like("%error%"))


@router.get("")
def get_overview(db: Session = Depends(get_db)) -> dict:
    def count_files(*criteria) -> int:
        q = db.query(func.count(WorkspaceFile.id)).filter(
            WorkspaceFile.is_deleted == False  # noqa: E712
        )
        for c in criteria:
            q = q.filter(c)
        return int(q.scalar() or 0)

    processed = count_files()
    errors = count_files(WorkspaceFile.status.in_(_ERROR_STATUSES))
    successful = count_files(WorkspaceFile.status.in_(_READY_STATUSES))
    resolved = count_files(WorkspaceFile.status.in_(_RESOLVED_STATUSES))

    # Contadores autoritativos do card "Resumo de Erros" (Home). COUNT O(1),
    # sem depender do array paginado (teto 1000) do navegador. Mesma semantica
    # atual do front para os numeros baterem:
    #   - workspaceErrorCount  -> playground_status em erro (predicado `Ka`)
    #   - automationErrorCount -> status em error/failed
    #   - manualActionCount    -> status == manual_review
    workspace_error_count = count_files(_playground_error_criteria())
    automation_error_count = errors
    manual_action_count = count_files(WorkspaceFile.status.in_(_MANUAL_STATUSES))

    automations_registered = int(
        db.query(func.count(Automation.id))
        .filter(Automation.is_deleted == False)  # noqa: E712
        .scalar()
        or 0
    )
    workspaces_total = int(
        db.query(func.count(Workspace.id))
        .filter(Workspace.is_deleted == False)  # noqa: E712
        .scalar()
        or 0
    )

    return {
        "processedFiles": processed,          # total de arquivos (nao deletados)
        "errorFiles": errors,                 # status error/failed
        "successfulFiles": successful,        # status ready
        "resolvedFiles": resolved,            # status resolved
        "errorsResolved": resolved,           # alias consumido pela pizza do Home
        # Card "Resumo de Erros" (Home): contagens autoritativas por COUNT.
        "workspaceErrorCount": workspace_error_count,
        "automationErrorCount": automation_error_count,
        "manualActionCount": manual_action_count,
        "automationsRegistered": automations_registered,
        "activeWorkspaces": workspaces_total,
        "totalWorkspaces": workspaces_total,
    }
