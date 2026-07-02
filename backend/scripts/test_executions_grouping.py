r"""
test_executions_grouping.py -- Testes deterministicos (sem navegador, SQLite em memoria) do
AGRUPAMENTO de execucoes no Historico ('list_executions' em app/routers/executions.py).

Contexto: uma inicializacao de automacao pode gerar MAIS DE UMA task
'upload_files_to_workspace' (a raiz criada por create_upload_task_for_automation, e
reenvios de PDF criados pelo agente em process_monitor/process_convert_retry apos o
monitoramento). Antes desta mudanca, list_executions listava 1 LINHA POR TASK, inflando o
Historico. Agora, tasks de reenvio carregam 'origin_task_id' (propagado via **payload a
partir de 'source_upload_task_id', setado pelo backend em agents.py ao enfileirar o
monitoramento) apontando para a task raiz da inicializacao; list_executions agrupa por essa
raiz e devolve 1 linha agregada por inicializacao.

Cenarios cobertos:
  1. 1 inicializacao com 1 upload raiz + 2 reenvios (mesmo origin_task_id) -> list_executions
     devolve 1 UNICA linha, com total_files/success_count/error_count agregados (sem duplicar
     arquivos que aparecem em mais de uma task do grupo).
  2. 2 inicializacoes distintas (2 raizes, sem origin_task_id entre si) -> 2 linhas.
  3. Task legada sem origin_task_id (pre-existente antes desta mudanca) -> permanece como sua
     propria linha (nao e mesclada com nada).
  4. Agregacao de contagens: mesmo file_id presente na task raiz E na task de reenvio conta
     UMA unica vez no total_files/success_count do grupo.
  5. GET /executions/{id} (execution_detail) na raiz de um grupo devolve a mesma agregacao
     (mesmo total_files) que a linha da lista.

Uso: a partir de backend/  ->  .venv\Scripts\python.exe scripts\test_executions_grouping.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.session import Base  # noqa: E402
from app.models.agent import AgentTask  # noqa: E402
from app.models.automation import Automation  # noqa: E402
from app.models.file import WorkspaceFile  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402

import app.routers.executions as executions  # noqa: E402


PASS = 0
FAIL = 0


def check(condition: bool, message: str) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {message}")
    else:
        FAIL += 1
        print(f"  [FAIL] {message}")


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_common(db) -> tuple[Automation, Workspace, User]:
    aut = Automation(name="SPEC 226 Work in progress", status="active", folder_path="C:/monitor")
    ws = Workspace(name="WS SPEC 226")
    user = User(name="Agent User", email="agent@example.com", network_id="agent", password_hash="x")
    db.add_all([aut, ws, user])
    db.commit()
    db.refresh(aut)
    db.refresh(ws)
    db.refresh(user)
    return aut, ws, user


def make_file(db, automation_id, workspace_id, name, status="ready", playground_status="Ready", detection_task_id=None) -> WorkspaceFile:
    f = WorkspaceFile(
        file_name=name,
        automation_id=automation_id,
        workspace_id=workspace_id,
        status=status,
        playground_status=playground_status,
        detection_task_id=detection_task_id,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def make_task(
    db,
    task_type: str,
    payload: dict,
    status: str = "completed",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    created_by_id: int | None = None,
) -> AgentTask:
    task = AgentTask(
        task_type=task_type,
        status=status,
        payload_json=json.dumps(payload, ensure_ascii=False),
        created_by_id=created_by_id,
        started_at=started_at,
        completed_at=completed_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def scenario_1_and_4_single_initialization_grouped():
    """1 inicializacao (raiz + 2 reenvios) -> 1 linha agregada; sem duplicar arquivos."""
    print("\n[Scenario 1+4] 1 inicializacao com raiz + 2 reenvios de PDF -> 1 linha agregada")
    db = make_session()
    aut, ws, user = seed_common(db)

    t0 = datetime(2026, 7, 1, 22, 40, 0)

    # 3 arquivos detectados pela task raiz.
    f1 = make_file(db, aut.id, ws.id, "a.docx", status="uploaded", playground_status="Pending")
    f2 = make_file(db, aut.id, ws.id, "b.docx", status="uploaded", playground_status="Pending")
    f3 = make_file(db, aut.id, ws.id, "c.docx", status="ready", playground_status="Ready")
    for f in (f1, f2, f3):
        f.detection_task_id = None  # setado abaixo, apos criar a task raiz
    db.commit()

    root = make_task(
        db,
        "upload_files_to_workspace",
        {
            "automation_id": aut.id,
            "workspace_id": ws.id,
            "user_id": user.id,
            "files": [
                {"file_id": f1.id, "file_name": f1.file_name},
                {"file_id": f2.id, "file_name": f2.file_name},
                {"file_id": f3.id, "file_name": f3.file_name},
            ],
        },
        status="completed",
        started_at=t0,
        completed_at=t0 + timedelta(seconds=30),
        created_by_id=user.id,
    )
    for f in (f1, f2, f3):
        f.detection_task_id = root.id
    db.commit()

    # Reenvio 1 (PDF de a.docx e b.docx que nao ficaram Ready): origin_task_id = root.id.
    resend1 = make_task(
        db,
        "upload_files_to_workspace",
        {
            "automation_id": aut.id,
            "workspace_id": ws.id,
            "user_id": user.id,
            "origin_task_id": root.id,
            "source_upload_task_id": root.id,
            "start_monitoring_after_upload": False,
            "files": [
                {"file_id": f1.id, "file_name": "a.pdf", "original_file_name": "a.docx"},
                {"file_id": f2.id, "file_name": "b.pdf", "original_file_name": "b.docx"},
            ],
        },
        status="completed",
        started_at=t0 + timedelta(seconds=40),
        completed_at=t0 + timedelta(seconds=70),
        created_by_id=user.id,
    )
    # Apos reenvio: a.docx virou ready, b.docx ainda esta manual_review.
    f1.status = "ready"
    f1.playground_status = "Ready"
    f2.status = "manual_review"
    f2.playground_status = "Error"
    db.commit()

    # Reenvio 2 (segunda tentativa de b.docx, mesma inicializacao): origin_task_id = root.id.
    resend2 = make_task(
        db,
        "upload_files_to_workspace",
        {
            "automation_id": aut.id,
            "workspace_id": ws.id,
            "user_id": user.id,
            "origin_task_id": root.id,
            "start_monitoring_after_upload": False,
            "files": [{"file_id": f2.id, "file_name": "b_v2.pdf", "original_file_name": "b.docx"}],
        },
        status="completed",
        started_at=t0 + timedelta(seconds=80),
        completed_at=t0 + timedelta(seconds=100),
        created_by_id=user.id,
    )
    f2.status = "ready"
    f2.playground_status = "Ready"
    db.commit()

    rows = executions.list_executions(automation_id=None, status="", started_from="", started_to="", limit=100, db=db)
    check(len(rows) == 1, f"list_executions devolve 1 linha para a inicializacao (obtido: {len(rows)})")
    if rows:
        row = rows[0]
        check(row["run_code"] == f"TASK-{root.id:05d}", f"run_code e o da task RAIZ (obtido: {row['run_code']})")
        check(row["total_files"] == 3, f"total_files agregado = 3 sem duplicar (obtido: {row['total_files']})")
        check(row["success_count"] == 3, f"success_count agregado = 3 (obtido: {row['success_count']})")
        check(row["error_count"] == 0, f"error_count agregado = 0 (obtido: {row['error_count']})")
        check(row["summary"]["grouped_task_ids"] == [root.id, resend1.id, resend2.id] or sorted(row["summary"]["grouped_task_ids"]) == sorted([root.id, resend1.id, resend2.id]), f"grouped_task_ids contem as 3 tasks (obtido: {row['summary']['grouped_task_ids']})")
        check(row["started_at"] is not None, "started_at presente (o mais antigo do grupo)")
        check(row["finished_at"] is not None, "finished_at presente (todas as tasks do grupo terminaram)")

    # execution_detail na raiz deve bater com a mesma agregacao.
    detail = executions.execution_detail(root.id, db=db)
    check(detail["total_files"] == 3, f"execution_detail(root) agrega os mesmos 3 arquivos (obtido: {detail['total_files']})")

    # execution_detail chamado por um id de REENVIO (nao exposto na UI, mas deve resolver a raiz).
    detail_from_resend = executions.execution_detail(resend2.id, db=db)
    check(detail_from_resend["id"] == root.id, f"execution_detail(resend) resolve para a raiz (obtido id={detail_from_resend['id']})")

    return db, aut, root, resend1, resend2, (f1, f2, f3)


def scenario_2_two_independent_initializations():
    print("\n[Scenario 2] 2 inicializacoes distintas (sem origin_task_id entre si) -> 2 linhas")
    db = make_session()
    aut, ws, user = seed_common(db)
    t0 = datetime(2026, 7, 1, 22, 40, 0)
    t1 = datetime(2026, 7, 1, 22, 45, 0)

    f1 = make_file(db, aut.id, ws.id, "x.docx", status="ready", playground_status="Ready")
    task1 = make_task(
        db, "upload_files_to_workspace",
        {"automation_id": aut.id, "workspace_id": ws.id, "user_id": user.id, "files": [{"file_id": f1.id, "file_name": f1.file_name}]},
        status="completed", started_at=t0, completed_at=t0 + timedelta(seconds=20), created_by_id=user.id,
    )
    f1.detection_task_id = task1.id
    db.commit()

    f2 = make_file(db, aut.id, ws.id, "y.docx", status="ready", playground_status="Ready")
    task2 = make_task(
        db, "upload_files_to_workspace",
        {"automation_id": aut.id, "workspace_id": ws.id, "user_id": user.id, "files": [{"file_id": f2.id, "file_name": f2.file_name}]},
        status="completed", started_at=t1, completed_at=t1 + timedelta(seconds=20), created_by_id=user.id,
    )
    f2.detection_task_id = task2.id
    db.commit()

    rows = executions.list_executions(automation_id=None, status="", started_from="", started_to="", limit=100, db=db)
    check(len(rows) == 2, f"2 inicializacoes independentes -> 2 linhas (obtido: {len(rows)})")
    run_codes = {row["run_code"] for row in rows}
    check(run_codes == {f"TASK-{task1.id:05d}", f"TASK-{task2.id:05d}"}, f"run_codes correspondem as 2 raizes (obtido: {run_codes})")
    return db


def scenario_3_legacy_task_without_origin():
    print("\n[Scenario 3] Task legada sem origin_task_id -> permanece linha propria (nao mescla)")
    db = make_session()
    aut, ws, user = seed_common(db)
    t0 = datetime(2026, 7, 1, 22, 40, 0)
    t1 = datetime(2026, 7, 1, 22, 41, 0)

    f1 = make_file(db, aut.id, ws.id, "legacy1.docx", status="ready", playground_status="Ready")
    legacy1 = make_task(
        db, "upload_files_to_workspace",
        {"automation_id": aut.id, "workspace_id": ws.id, "user_id": user.id, "files": [{"file_id": f1.id, "file_name": f1.file_name}]},
        status="completed", started_at=t0, completed_at=t0 + timedelta(seconds=10), created_by_id=user.id,
    )
    f1.detection_task_id = legacy1.id
    db.commit()

    f2 = make_file(db, aut.id, ws.id, "legacy2.docx", status="ready", playground_status="Ready")
    legacy2 = make_task(
        db, "upload_files_to_workspace",
        {"automation_id": aut.id, "workspace_id": ws.id, "user_id": user.id, "files": [{"file_id": f2.id, "file_name": f2.file_name}]},
        status="completed", started_at=t1, completed_at=t1 + timedelta(seconds=10), created_by_id=user.id,
    )
    f2.detection_task_id = legacy2.id
    db.commit()

    rows = executions.list_executions(automation_id=None, status="", started_from="", started_to="", limit=100, db=db)
    check(len(rows) == 2, f"2 tasks legadas sem origin_task_id nunca se fundem (obtido: {len(rows)} linhas)")
    return db


def scenario_5_delete_group_cascades():
    print("\n[Scenario 5] DELETE /executions/{root_id} apaga o grupo inteiro (raiz + reenvios)")
    db, aut, root, resend1, resend2, files = scenario_1_and_4_single_initialization_grouped()
    result = executions.delete_execution(root.id, db=db)
    check(result["status"] == "deleted", "delete_execution retorna status=deleted")

    remaining = db.query(AgentTask).filter(AgentTask.is_deleted == False, AgentTask.task_type == "upload_files_to_workspace").count()
    check(remaining == 0, f"raiz + 2 reenvios todos marcados is_deleted (restantes: {remaining})")

    rows = executions.list_executions(automation_id=None, status="", started_from="", started_to="", limit=100, db=db)
    check(len(rows) == 0, f"linha agregada some do Historico apos exclusao (obtido: {len(rows)})")


def main() -> int:
    scenario_1_and_4_single_initialization_grouped()
    scenario_2_two_independent_initializations()
    scenario_3_legacy_task_without_origin()
    scenario_5_delete_group_cascades()

    print(f"\n=== RESULT: {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
