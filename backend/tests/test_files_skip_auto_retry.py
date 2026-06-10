"""Regressao: PUT /api/files que muda status para 'pending_retry' so deve auto-enfileirar
convert_and_retry_file no caminho MANUAL (dashboard). O fluxo interno do agente passa
skip_auto_retry=True para NAO duplicar o reenvio (o agente ja reenvia em lote).
"""

from app.models.agent import AgentTask
from app.models.file import WorkspaceFile
from app.routers.files import update_file


def _make_error_file(db) -> WorkspaceFile:
    f = WorkspaceFile(file_name="x.docx", status="error", is_deleted=False, original_path="C:/monitorada/x.docx")
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def _retry_task_count(db) -> int:
    return db.query(AgentTask).filter(AgentTask.task_type == "convert_and_retry_file").count()


def test_pending_retry_manual_cria_convert_and_retry(db_session):
    f = _make_error_file(db_session)
    update_file(f.id, {"status": "pending_retry"}, db_session)
    assert _retry_task_count(db_session) == 1
    db_session.refresh(f)
    assert f.status == "pending_retry"


def test_pending_retry_com_skip_auto_retry_nao_cria_task(db_session):
    f = _make_error_file(db_session)
    update_file(f.id, {"status": "pending_retry", "skip_auto_retry": True}, db_session)
    assert _retry_task_count(db_session) == 0
    db_session.refresh(f)
    # O status muda normalmente; apenas o gatilho automatico de reenvio individual fica suprimido.
    assert f.status == "pending_retry"
    # O flag nao deve virar coluna do modelo.
    assert not hasattr(f, "skip_auto_retry") or getattr(f, "skip_auto_retry", None) in (None, True)
