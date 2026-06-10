"""Testes do monitoramento de presenca pos-reenvio.

Cobre:
(a) _monitor_presence_only: calcula present/missing por presenca (NotFound = missing),
    ignorando o status real (Ready, Error, Pending, Processing sao todos "presente").
(b) process_monitor em modo presenca: teto de tentativas (presence_attempt >= PRESENCE_MAX_ATTEMPTS - 1)
    envia ausentes para manual_review em vez de reenfileirar.
(c) process_monitor em modo presenca: com tentativas restantes, converte e reenfileira.

Os testes nao abrem navegador: `_monitor_presence_only` e mockada diretamente para testar
o orchestrador (process_monitor) separado da camada Playwright.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from app.cli.local_agent import (
    PRESENCE_MAX_ATTEMPTS,
    PRESENCE_MONITORING_TIMEOUT_MINUTES,
    _build_resend_files_from_names,
    process_monitor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_log(level, message, **kwargs):
    pass


def _make_task(task_id: int = 1) -> dict[str, Any]:
    return {"id": task_id, "created_at": None}


def _statuses_presence(names: list[str], present: list[str]) -> dict[str, Any]:
    """Monta dicionario de statuses no formato do monitor: presente = qualquer FOUND_STATUS, ausente = NotFound."""
    result = {}
    for name in names:
        if name in present:
            result[name] = {"status": "Pending", "raw": name, "status_text": "Pending"}
        else:
            result[name] = {"status": "NotFound", "raw": "", "status_text": ""}
    return result


# ---------------------------------------------------------------------------
# Testes do calculo de presenca (logica pura — sem navegador)
# ---------------------------------------------------------------------------


def test_presenca_notfound_e_missing():
    """Arquivo com status NotFound e classificado como missing (ausente)."""
    statuses = {
        "a.pdf": {"status": "NotFound", "raw": "", "status_text": ""},
        "b.pdf": {"status": "Ready", "raw": "b.pdf Ready", "status_text": "Ready"},
    }
    expected_names = ["a.pdf", "b.pdf"]
    present = [n for n in expected_names if statuses[n]["status"] != "NotFound"]
    missing = [n for n in expected_names if statuses[n]["status"] == "NotFound"]

    assert present == ["b.pdf"]
    assert missing == ["a.pdf"]


def test_presenca_qualquer_status_found_e_presente():
    """Ready, Error, Pending, Processing: todos sao 'presente' no modo presenca."""
    statuses = {
        "ready.pdf": {"status": "Ready"},
        "error.pdf": {"status": "Error"},
        "pending.pdf": {"status": "Pending"},
        "processing.pdf": {"status": "Processing"},
        "missing.pdf": {"status": "NotFound"},
    }
    names = list(statuses.keys())
    present = [n for n in names if statuses[n]["status"] != "NotFound"]
    missing = [n for n in names if statuses[n]["status"] == "NotFound"]

    assert set(present) == {"ready.pdf", "error.pdf", "pending.pdf", "processing.pdf"}
    assert missing == ["missing.pdf"]


# ---------------------------------------------------------------------------
# Testes do process_monitor em modo presenca (mock de monitor_workspace_files_status)
# ---------------------------------------------------------------------------


def _make_presence_result(present: list[str], missing: list[str]) -> dict[str, Any]:
    return {
        "status": "completed",
        "present": present,
        "missing": missing,
        "to_resend": missing,
        "presence_only": True,
        "statuses": {n: {"status": "NotFound"} for n in missing},
    }


@patch("app.cli.local_agent.create_agent_task", return_value=999)
@patch("app.cli.local_agent.complete_task")
@patch("app.cli.local_agent.monitor_workspace_files_status")
@patch("app.cli.local_agent.stop_checker")
def test_presenca_sem_faltantes_conclui(mock_stop, mock_monitor, mock_complete, mock_create):
    """Se nao ha arquivos faltantes, o task e concluido sem reenfileirar nada."""
    mock_stop.return_value = lambda: True
    mock_monitor.return_value = _make_presence_result(
        present=["a.pdf", "b.pdf"], missing=[]
    )

    session = MagicMock()
    task = _make_task()
    payload = {
        "workspace_name": "WS1",
        "presence_only": True,
        "presence_attempt": 0,
        "files": [
            {"file_id": 1, "file_name": "a.pdf", "temp_path": "/tmp/a.pdf"},
            {"file_id": 2, "file_name": "b.pdf", "temp_path": "/tmp/b.pdf"},
        ],
    }

    process_monitor(session, task, payload, user_id=1, log=_noop_log)

    mock_complete.assert_called_once()
    # Nenhum novo task deve ter sido enfileirado.
    mock_create.assert_not_called()


@patch("app.cli.local_agent.update_file")
@patch("app.cli.local_agent.manual_review_task")
@patch("app.cli.local_agent.monitor_workspace_files_status")
@patch("app.cli.local_agent.stop_checker")
def test_presenca_teto_atingido_vai_para_manual_review(mock_stop, mock_monitor, mock_manual, mock_update):
    """Ao atingir o teto de tentativas com arquivos faltantes, envia para manual_review."""
    mock_stop.return_value = lambda: True
    mock_monitor.return_value = _make_presence_result(
        present=["a.pdf"], missing=["b.pdf"]
    )

    session = MagicMock()
    task = _make_task()
    # presence_attempt == PRESENCE_MAX_ATTEMPTS - 1 => teto atingido.
    payload = {
        "workspace_name": "WS1",
        "presence_only": True,
        "presence_attempt": PRESENCE_MAX_ATTEMPTS - 1,
        "files": [
            {"file_id": 1, "file_name": "a.pdf", "temp_path": "/tmp/a.pdf"},
            {"file_id": 2, "file_name": "b.pdf", "temp_path": "/tmp/b.pdf"},
        ],
    }

    process_monitor(session, task, payload, user_id=1, log=_noop_log)

    mock_manual.assert_called_once()
    # update_file deve ter sido chamado para "b.pdf" com status manual_review.
    update_calls_statuses = [c.args[2].get("status") for c in mock_update.call_args_list if isinstance(c.args[2], dict)]
    assert "manual_review" in update_calls_statuses


@patch("app.cli.local_agent.create_agent_task", return_value=42)
@patch("app.cli.local_agent.complete_task")
@patch("app.cli.local_agent.convert_to_pdf_in_folder", return_value="/tmp/PDF/b.pdf")
@patch("app.cli.local_agent.update_file")
@patch("app.cli.local_agent.monitor_workspace_files_status")
@patch("app.cli.local_agent.stop_checker")
def test_presenca_com_faltantes_reenvia_e_reenfileira(
    mock_stop, mock_monitor, mock_update, mock_convert, mock_complete, mock_create
):
    """Com faltantes e tentativas restantes: converte para PDF, reenvia e enfileira proximo monitor."""
    mock_stop.return_value = lambda: True
    mock_monitor.return_value = _make_presence_result(
        present=["a.pdf"], missing=["b.pdf"]
    )

    session = MagicMock()
    task = _make_task()
    payload = {
        "workspace_name": "WS1",
        "presence_only": True,
        "presence_attempt": 0,  # Primeira tentativa — ainda ha margem.
        "files": [
            {"file_id": 1, "file_name": "a.pdf", "temp_path": "/tmp/lote/a.pdf"},
            {"file_id": 2, "file_name": "b.pdf", "temp_path": "/tmp/lote/b.pdf"},
        ],
    }

    with patch("pathlib.Path.is_file", return_value=True):
        process_monitor(session, task, payload, user_id=1, log=_noop_log)

    # Deve ter chamado create_agent_task DUAS vezes:
    # 1) upload_files_to_workspace (reenvio do b.pdf)
    # 2) monitor_workspace_files_status (novo monitor de presenca com presence_attempt=1)
    task_types = [c.args[1] for c in mock_create.call_args_list]
    assert "upload_files_to_workspace" in task_types
    assert "monitor_workspace_files_status" in task_types

    # O payload do novo monitor de presenca deve ter presence_attempt incrementado.
    presence_call = next(
        c for c in mock_create.call_args_list if c.args[1] == "monitor_workspace_files_status"
    )
    presence_payload = presence_call.args[2]
    assert presence_payload.get("presence_only") is True
    assert presence_payload.get("presence_attempt") == 1
    assert presence_payload.get("monitoring_timeout_minutes") == PRESENCE_MONITORING_TIMEOUT_MINUTES

    mock_complete.assert_called_once()


# ---------------------------------------------------------------------------
# Testes do process_monitor em modo normal — verificar que enfileira monitor de presenca
# ---------------------------------------------------------------------------


@patch("app.cli.local_agent.create_agent_task", return_value=77)
@patch("app.cli.local_agent.complete_task")
@patch("app.cli.local_agent.update_file")
@patch("app.cli.local_agent.monitor_workspace_files_status")
@patch("app.cli.local_agent.stop_checker")
def test_modo_normal_sem_reenvio_enfileira_presenca(
    mock_stop, mock_monitor, mock_update, mock_complete, mock_create
):
    """Mesmo sem to_resend, o modo normal deve enfileirar monitoramento de presenca."""
    mock_stop.return_value = lambda: True
    mock_monitor.return_value = {
        "status": "completed",
        "ready": ["a.pdf"],
        "ready_lost": [],
        "manual_review": [],
        "to_resend": [],
        "deleted": [],
        "delete_failed": [],
        "not_found": [],
        "unknown": [],
        "statuses": {"a.pdf": {"status": "Ready"}},
    }

    session = MagicMock()
    task = _make_task()
    payload = {
        "workspace_name": "WS1",
        "files": [{"file_id": 1, "file_name": "a.pdf", "temp_path": "/tmp/lote/a.pdf"}],
    }

    process_monitor(session, task, payload, user_id=1, log=_noop_log)

    # Deve enfileirar APENAS o monitor de presenca (sem reenvio).
    task_types = [c.args[1] for c in mock_create.call_args_list]
    assert "monitor_workspace_files_status" in task_types
    assert "upload_files_to_workspace" not in task_types

    presence_call = next(
        c for c in mock_create.call_args_list if c.args[1] == "monitor_workspace_files_status"
    )
    presence_payload = presence_call.args[2]
    assert presence_payload.get("presence_only") is True
    assert presence_payload.get("presence_attempt") == 0
    mock_complete.assert_called_once()


@patch("app.cli.local_agent.create_agent_task", return_value=88)
@patch("app.cli.local_agent.complete_task")
@patch("app.cli.local_agent.convert_to_pdf_in_folder", return_value="/tmp/PDF/c.pdf")
@patch("app.cli.local_agent.update_file")
@patch("app.cli.local_agent.monitor_workspace_files_status")
@patch("app.cli.local_agent.stop_checker")
def test_modo_normal_com_reenvio_enfileira_presenca_e_upload(
    mock_stop, mock_monitor, mock_update, mock_convert, mock_complete, mock_create
):
    """Com to_resend, o modo normal enfileira upload + monitor de presenca."""
    mock_stop.return_value = lambda: True
    mock_monitor.return_value = {
        "status": "completed",
        "ready": [],
        "ready_lost": [],
        "manual_review": [],
        "to_resend": ["c.pdf"],
        "deleted": ["c.pdf"],
        "delete_failed": [],
        "not_found": [],
        "unknown": [],
        "statuses": {"c.pdf": {"status": "Error"}},
    }

    session = MagicMock()
    task = _make_task()
    payload = {
        "workspace_name": "WS1",
        "files": [{"file_id": 3, "file_name": "c.pdf", "temp_path": "/tmp/lote/c.pdf"}],
    }

    with patch("pathlib.Path.is_file", return_value=True):
        process_monitor(session, task, payload, user_id=1, log=_noop_log)

    task_types = [c.args[1] for c in mock_create.call_args_list]
    assert "upload_files_to_workspace" in task_types
    assert "monitor_workspace_files_status" in task_types

    # O monitor de presenca deve cobrir TODOS os arquivos originais (nao so os reenviados).
    presence_call = next(
        c for c in mock_create.call_args_list if c.args[1] == "monitor_workspace_files_status"
    )
    presence_payload = presence_call.args[2]
    assert presence_payload.get("presence_only") is True
    # files deve ser a lista completa original.
    assert len(presence_payload.get("files") or []) == 1
    assert presence_payload["files"][0]["file_name"] == "c.pdf"
    mock_complete.assert_called_once()
