from __future__ import annotations

import ast
import hashlib
import json
import os
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

from app.core.config import SUPPORTED_ENVIRONMENTS, environment_scope, settings
from app.services.automation_staging import (
    copy_files_to_staging,
    enabled_extensions_from_config,
    folder_path_diagnostics,
    no_files_copied_message,
    no_files_message,
    normalize_folder_path,
    scan_monitored_folder,
)
from app.services.playwright.errors import ManualReviewRequired, PlaygroundLoginRequired, UnsupportedFormat
from app.services.playwright.browser import session_dir_for_user
from app.services.playwright.playground_login import connect_playground_session
from app.services.playwright.playground_monitor import monitor_workspace_files_status
from app.services.playwright.playground_upload import convert_file_to_pdf, convert_to_pdf_in_folder, upload_files_to_workspace
from app.services.playwright.playground_users import add_playground_user_to_workspace
from app.services.playwright.playground_workspace import create_playground_workspace
from app.services.playwright.teams_delivery import (
    deliver_file_teams_playwright,
    deliver_report_teams_playwright,
    TeamsLoginRequired,
)
from app.services import teams_png_watch


API_BASE_URL = os.getenv("AUTOMATION_HUB_API_URL", "http://127.0.0.1:8000")
AGENT_NAME = os.getenv("AUTOMATION_HUB_AGENT_NAME", "local-dev-agent-1")
HTTP_TIMEOUT = 15
OFFICIAL_TASK_TYPES = {
    "connect_playground_session",
    "create_playground_workspace",
    "add_playground_user_to_workspace",
    "upload_files_to_workspace",
    "monitor_workspace_files_status",
    "convert_and_retry_file",
    "deliver_report_teams_playwright",
    "deliver_png_teams_playwright",
}
PLAYWRIGHT_TASK_TYPES = set(OFFICIAL_TASK_TYPES)
FOLDER_REPORT_SOURCE = "folder_monitoring_detection"
FOLDER_DETECTION_SOURCE = "folder_monitoring"
REPORTABLE_TERMINAL_STATUSES = {
    "folder_not_found",
    "folder_inaccessible",
    "folder_scan_failed",
    "file_signature_failed",
    "no_files_copied",
}
BATCH_CHECKPOINT_ATTEMPTS = 3


def request_json(session: requests.Session, method: str, path: str, payload: Optional[dict] = None) -> dict:
    kwargs = {"timeout": HTTP_TIMEOUT}
    if method.upper() != "GET":
        kwargs["json"] = payload or {}
    response = session.request(method, f"{API_BASE_URL}{path}", **kwargs)
    if response.status_code >= 400:
        # raise_for_status() sozinho descarta o corpo da resposta, entao um 500
        # aparecia no log apenas como "Internal Server Error" sem a causa. Anexamos
        # o corpo (truncado) para que o motivo real do backend fique registrado.
        detail = (response.text or "").strip().replace("\n", " ")
        if len(detail) > 500:
            detail = detail[:500] + "..."
        raise requests.HTTPError(
            f"{response.status_code} {response.reason} for {method} {path}"
            + (f" | body: {detail}" if detail else ""),
            response=response,
        )
    if not response.content:
        return {}
    return response.json()


def post_json(session: requests.Session, path: str, payload: Optional[dict] = None) -> dict:
    return request_json(session, "POST", path, payload)


def put_json(session: requests.Session, path: str, payload: Optional[dict] = None) -> dict:
    return request_json(session, "PUT", path, payload)


def get_json(session: requests.Session, path: str) -> Any:
    return request_json(session, "GET", path)


class AutomationStopped(Exception):
    pass


def parse_payload(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("payload_json")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def resolve_user_id(task: dict[str, Any], payload: dict[str, Any]) -> Optional[int]:
    user_id = payload.get("user_id") or payload.get("requested_by") or task.get("created_by_id")
    if user_id in [None, ""]:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def task_logger(session: requests.Session, task_id: int, default_automation_id: int | None = None):
    def log(
        level: str,
        message: str,
        *,
        automation_id: int | None = None,
        file_id: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        print(f"[{level.upper()}] task {task_id}: {message}", flush=True)
        try:
            post_json(
                session,
                f"/api/agents/tasks/{task_id}/log",
                {
                    "level": level,
                    "message": message,
                    "automation_id": automation_id if automation_id is not None else default_automation_id,
                    "file_id": file_id,
                    "metadata": metadata,
                },
            )
        except Exception as exc:
            print(f"[WARNING] Falha ao registrar log da task {task_id}: {exc}", flush=True)

    return log


def local_report_metadata(report_event: str, metadata: dict | None = None) -> dict:
    return {
        **(metadata or {}),
        "report_source": FOLDER_REPORT_SOURCE,
        "report_event": report_event,
    }


def staging_report_logger(log, automation_id: int | None):
    def staged_log(level: str, message: str, *, metadata: dict | None = None, **kwargs) -> None:
        event = None
        if message.startswith("Subpasta inacessivel durante scan."):
            event = "subfolder_inaccessible"
        elif message.startswith("Item inacessivel durante scan."):
            event = "item_inaccessible"
        elif message.startswith("Arquivo nao copiado para temporario:"):
            event = "copy_failed"
        if event:
            level = "error"
            metadata = local_report_metadata(event, metadata)
        log(level, message, automation_id=automation_id, metadata=metadata, **kwargs)

    return staged_log


def should_generate_folder_report(payload: dict[str, Any], terminal_result: dict[str, Any] | None) -> bool:
    return False


def request_automatic_folder_report(session: requests.Session, task_id: int, automation_id: int | None, log) -> None:
    try:
        result = post_json(session, f"/api/agents/tasks/{task_id}/folder-monitoring-report", {})
        report = result.get("report") or {}
        action = "gerado" if result.get("created") else "ja existente"
        log(
            "info",
            f"Relatorio automatico de monitoramento {action}.",
            automation_id=automation_id,
            metadata={"report_id": report.get("id"), "source_task_id": task_id},
        )
    except Exception as exc:
        log(
            "error",
            "Falha ao gerar relatorio automatico do monitoramento; a automacao web continuara.",
            automation_id=automation_id,
            metadata=local_report_metadata("automatic_report_generation_failed", {"error": str(exc), "source_task_id": task_id}),
        )


def complete_task(session: requests.Session, task_id: int, result: dict[str, Any], extra: dict[str, Any] | None = None) -> None:
    payload = {"result": result}
    if extra:
        payload.update(extra)
    post_json(session, f"/api/agents/tasks/{task_id}/complete", payload)


def fail_task(session: requests.Session, task_id: int, message: str, result: dict[str, Any] | None = None) -> None:
    post_json(session, f"/api/agents/tasks/{task_id}/fail", {"error_message": message, "result": result or {}})


def manual_review_task(session: requests.Session, task_id: int, message: str, result: dict[str, Any] | None = None) -> None:
    post_json(session, f"/api/agents/tasks/{task_id}/manual-review", {"error_message": message, "result": result or {}})


def cancel_task(session: requests.Session, task_id: int, message: str) -> None:
    post_json(session, f"/api/agents/tasks/{task_id}/cancel", {"message": message})


def ensure_automation_active(session: requests.Session, automation_id: int | None, log) -> bool:
    if not automation_id:
        return True
    try:
        automation = get_json(session, f"/api/automations/{automation_id}")
    except Exception as exc:
        log("warning", f"Nao foi possivel checar status da automacao: {exc}", automation_id=automation_id)
        return True
    status = str(automation.get("status") or "").lower()
    if automation.get("is_deleted") or status in {"stopped", "cancelled", "archived", "deleted"}:
        log("warning", f"Automacao interrompida: {status or 'deleted'}.", automation_id=automation_id)
        return False
    return True


def stop_checker(session: requests.Session, task_id: int, automation_id: int | None, log):
    def should_continue() -> bool:
        if ensure_automation_active(session, automation_id, log):
            return True
        raise AutomationStopped("Automacao parada pelo usuario.")

    return should_continue


def task_stop_checker(session: requests.Session, task_id: int, automation_id: int | None, log):
    """Como stop_checker, mas tambem detecta o cancelamento da PROPRIA task (GET
    /api/agents/tasks/{id}/status). Usado nas tarefas 'rapidas' (connect_playground_session /
    create_playground_workspace / add_playground_user_to_workspace) que podem nao ter
    automation_id -- assim o botao 'parar' interrompe ate um login manual em andamento, que so
    sairia pelo timeout de MANUAL_LOGIN_TIMEOUT_MINUTES."""
    def should_continue() -> bool:
        if not ensure_automation_active(session, automation_id, log):
            raise AutomationStopped("Automacao parada pelo usuario.")
        try:
            info = get_json(session, f"/api/agents/tasks/{task_id}/status")
        except Exception:
            # Falha transitoria de rede nao deve abortar a tarefa; tenta de novo no proximo ciclo.
            return True
        status = str(info.get("status") or "").lower()
        if info.get("is_deleted") or status == "cancelled":
            raise AutomationStopped("Task cancelada pelo usuario.")
        return True

    return should_continue


def create_agent_task(session: requests.Session, task_type: str, payload: dict[str, Any], max_attempts: int | None = None) -> int:
    user_id = payload.get("user_id") or payload.get("requested_by")
    response = post_json(
        session,
        "/api/agents/tasks",
        {
            "task_type": task_type,
            "payload": payload,
            "created_by_id": user_id,
            "max_attempts": max_attempts or payload.get("max_attempts") or 3,
        },
    )
    return int(response["task_id"])


def update_task_payload(session: requests.Session, task_id: int, payload_patch: dict[str, Any]) -> None:
    put_json(session, f"/api/agents/tasks/{task_id}/payload", {"payload_patch": payload_patch})


def checkpoint_uploaded_batch(
    session: requests.Session,
    task_id: int,
    automation_id: int | None,
    batch_number: int,
    batch_folder_path: str | None,
    uploaded_files: list[dict[str, Any]],
    log,
    should_continue=None,
) -> dict[str, Any]:
    request_payload = {
        "batch_number": batch_number,
        "batch_folder_path": batch_folder_path,
        "uploaded_files": uploaded_files,
    }
    last_error = None
    for attempt in range(1, BATCH_CHECKPOINT_ATTEMPTS + 1):
        if should_continue:
            should_continue()
        try:
            response = post_json(session, f"/api/agents/tasks/{task_id}/batch-complete", request_payload)
            log(
                "info",
                f"Checkpoint persistido para lote {batch_number}.",
                automation_id=automation_id,
                metadata={
                    "batch_number": batch_number,
                    "batch_folder_path": batch_folder_path,
                    "monitor_task_id": response.get("monitor_task_id"),
                    "checkpoint_status": response.get("status"),
                },
            )
            return response
        except Exception as exc:
            last_error = exc
            log(
                "warning",
                f"Falha ao persistir checkpoint do lote {batch_number}; tentativa {attempt} de {BATCH_CHECKPOINT_ATTEMPTS}.",
                automation_id=automation_id,
                metadata={"batch_number": batch_number, "batch_folder_path": batch_folder_path, "error": str(exc)},
            )
            if attempt < BATCH_CHECKPOINT_ATTEMPTS:
                # Backoff progressivo (1s, 2s, 4s...) para absorver instabilidades breves de rede
                # antes de escalar para revisao manual.
                time.sleep(2 ** (attempt - 1))
    raise ManualReviewRequired(
        f"Lote {batch_number} pode ter sido enviado ao Playground, mas o checkpoint nao foi persistido; "
        "nenhum lote posterior sera enviado ate revisao."
    ) from last_error


def resolve_batch_size(payload: dict[str, Any] | None = None, default: int | None = None) -> int:
    """Tamanho do lote de upload: payload['batch_size'] (ou 'default') -> settings.UPLOAD_BATCH_SIZE,
    sempre >= 1. Centraliza o parsing antes duplicado em 4 pontos, para a regra de fallback nunca
    divergir silenciosamente entre os caminhos de upload e de reenvio."""
    raw = (payload or {}).get("batch_size")
    fallback = default if default is not None else settings.UPLOAD_BATCH_SIZE
    try:
        return max(1, int(raw or fallback))
    except (TypeError, ValueError):
        return max(1, int(settings.UPLOAD_BATCH_SIZE))


def update_automation_status(session: requests.Session, automation_id: int | None, status: str) -> None:
    if not automation_id:
        return
    try:
        put_json(session, f"/api/automations/{automation_id}/status", {"status": status})
    except Exception as exc:
        print(f"[WARNING] Falha ao atualizar status da automacao {automation_id}: {exc}", flush=True)


def update_file(session: requests.Session, file_id: int | None, payload: dict[str, Any]) -> None:
    if not file_id:
        return
    try:
        put_json(session, f"/api/files/{file_id}", payload)
    except Exception as exc:
        print(f"[WARNING] Falha ao atualizar arquivo {file_id}: {exc}", flush=True)


def register_file(session: requests.Session, payload: dict[str, Any]) -> dict[str, Any]:
    return post_json(session, "/api/files", payload)


def resolve_registered_file(session: requests.Session, response: dict[str, Any], file_payload: dict[str, Any]) -> dict[str, Any]:
    if response.get("id"):
        return response
    automation_id = file_payload.get("automation_id")
    search = quote(str(file_payload.get("file_name") or ""))
    query = f"?search={search}&limit=20"
    if automation_id:
        query = f"?automation_id={automation_id}&search={search}&limit=20"
    try:
        items = get_json(session, f"/api/files{query}")
    except Exception:
        return response
    if not isinstance(items, list):
        return response
    expected_temp = str(file_payload.get("temp_path") or "")
    expected_name = str(file_payload.get("file_name") or "")
    for item in items:
        if expected_temp and str(item.get("temp_path") or "") == expected_temp:
            return item
    for item in items:
        if expected_name and str(item.get("file_name") or "") == expected_name:
            return item
    return response


def enabled_extensions_from_payload(payload: dict[str, Any]) -> set[str]:
    return enabled_extensions_from_config(
        {
            "file_types": payload.get("file_types") or [],
            "enabled_extensions": payload.get("enabled_extensions") or [],
        }
    )


def normalized_source_key(value: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(value)))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_iso_to_timestamp(value: str | None) -> float | None:
    """Converte string ISO 8601 (com ou sem offset de fuso) para POSIX timestamp float.

    Aceita formatos como "2024-01-15T10:30:00-03:00", "2024-01-15T10:30:00Z" e
    "2024-01-15T10:30:00" (naive, tratado como UTC por seguranca).
    Retorna None se a conversao falhar.
    """
    if not value:
        return None
    import datetime as _dt
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            # String sem fuso: assume UTC (valores armazenados pelo backend sao UTC naive)
            parsed = parsed.replace(tzinfo=_dt.timezone.utc)
        return parsed.timestamp()
    except (ValueError, TypeError):
        return None


# Tipo do baseline: source_key -> {"hashes": set[str], "last_ts": float | None}
# "last_ts" e o maior timestamp POSIX de uploaded_at ou ready_at conhecido para aquele caminho.
# Usado como fallback quando content_sha256 nao foi armazenado (registros legados ou migrados).
BaselineEntry = dict  # {"hashes": set[str], "last_ts": float | None}


def uploaded_content_baseline(
    session: requests.Session,
    automation_id: int | None,
    log,
) -> dict[str, BaselineEntry]:
    """Retorna baseline de arquivos ja processados com sucesso para a automacao.

    Estrutura retornada:
        {source_key: {"hashes": set_of_sha256, "last_ts": posix_float_or_None}}

    - Se "hashes" nao esta vazio: arquivo e considerado inalterado se seu sha256 atual
      estiver no set (comparacao de conteudo exata).
    - Se "hashes" esta vazio mas "last_ts" nao e None: arquivo e considerado inalterado
      se seu mtime no disco for <= last_ts (fallback para registros legados sem sha256).
    - Se ambos estao vazios/None: trata como nao visto anteriormente (nunca re-envia sem
      motivo, mas isso nao deveria ocorrer pois o filtro do backend so retorna
      registros com uploaded_at preenchido ou status terminal de sucesso).
    """
    if not automation_id:
        return {}
    rows = get_json(session, f"/api/files/upload-baseline/{automation_id}")
    if not isinstance(rows, list):
        raise RuntimeError("Resposta invalida ao consultar baseline de arquivos enviados.")
    baseline: dict[str, BaselineEntry] = {}
    no_hash_count = 0
    for row in rows:
        if not isinstance(row, dict) or not row.get("original_path"):
            continue
        source_key = normalized_source_key(row["original_path"])
        # Mantemos apenas a entrada mais recente por caminho (rows ja ordenados por
        # uploaded_at DESC, id DESC pelo backend).
        if source_key in baseline:
            continue
        hashes: set[str] = set()
        if row.get("content_sha256"):
            hashes.add(str(row["content_sha256"]))
        else:
            no_hash_count += 1
        # last_ts: maior entre uploaded_at e ready_at para comparacao de mtime
        ts_uploaded = _parse_iso_to_timestamp(row.get("uploaded_at"))
        ts_ready = _parse_iso_to_timestamp(row.get("ready_at"))
        last_ts: float | None = None
        if ts_uploaded is not None and ts_ready is not None:
            last_ts = max(ts_uploaded, ts_ready)
        elif ts_uploaded is not None:
            last_ts = ts_uploaded
        elif ts_ready is not None:
            last_ts = ts_ready
        baseline[source_key] = {"hashes": hashes, "last_ts": last_ts}
    log(
        "info",
        "Baseline de arquivos enviados carregado.",
        automation_id=automation_id,
        metadata={"tracked_paths": len(baseline), "no_hash_count": no_hash_count},
    )
    return baseline


def prepare_folder_upload_payload(
    session: requests.Session,
    task: dict[str, Any],
    payload: dict[str, Any],
    log,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if payload.get("files"):
        return payload, None
    folder_value = payload.get("folder_path") or payload.get("source_folder_path")
    if not folder_value:
        return payload, None

    task_id = int(task["id"])
    automation_id = payload.get("automation_id")
    workspace_id = payload.get("workspace_id")
    diagnostics = folder_path_diagnostics(str(folder_value))
    normalized_folder = diagnostics.get("normalized_path")
    if not normalized_folder:
        message = "Pasta monitorada vazia no payload da automacao."
        log("warning", message, automation_id=automation_id, metadata=diagnostics)
        return payload, {"status": "no_files", "message": message}

    folder = Path(normalized_folder)
    log("info", "Preparacao de arquivos iniciada no agente local.", automation_id=automation_id, metadata={**diagnostics, "folder_path": normalized_folder})
    try:
        folder_exists = folder.exists()
        folder_is_dir = folder.is_dir()
    except OSError as exc:
        message = f"Pasta monitorada inacessivel: {exc}"
        log("error", message, automation_id=automation_id, metadata=local_report_metadata("folder_inaccessible", {**diagnostics, "folder_path": normalized_folder, "error": str(exc)}))
        return payload, {"status": "folder_inaccessible", "message": message, "folder_path": normalized_folder, "path_diagnostics": diagnostics}
    if not folder_exists or not folder_is_dir:
        message = "Pasta monitorada nao encontrada ou nao e diretorio."
        log(
            "error",
            message,
            automation_id=automation_id,
            metadata=local_report_metadata("folder_not_found", {**diagnostics, "folder_path": normalized_folder, "exists": folder_exists, "is_dir": folder_is_dir}),
        )
        return payload, {"status": "folder_not_found", "message": message, "folder_path": normalized_folder, "path_diagnostics": diagnostics}

    enabled_exts = enabled_extensions_from_payload(payload)
    stage_log = staging_report_logger(log, automation_id)
    try:
        candidate_files, scan_stats = scan_monitored_folder(folder, enabled_exts, log=stage_log)
    except OSError as exc:
        message = f"Pasta monitorada nao pode ser listada: {exc}"
        log("error", message, automation_id=automation_id, metadata=local_report_metadata("folder_scan_failed", {**diagnostics, "folder_path": normalized_folder, "error": str(exc)}))
        return payload, {"status": "folder_scan_failed", "message": message, "folder_path": normalized_folder, "path_diagnostics": diagnostics}

    scan_stats["matched_source_files"] = len(candidate_files)
    full_execution = bool(payload.get("full_execution"))
    baseline = uploaded_content_baseline(session, automation_id, log)
    selected_files: list[Path] = []
    source_metadata: dict[str, dict[str, str]] = {}
    skipped_unchanged: list[str] = []
    hash_failures: list[dict[str, str]] = []
    classifications = {"new": 0, "updated": 0, "audit_duplicate": 0}
    for source in candidate_files:
        source_key = normalized_source_key(source)
        prior_entry = baseline.get(source_key)

        # Deteccao SOMENTE por data de modificacao (mtime) -- NAO le/hasheia o conteudo.
        # E o criterio do fluxo: nas execucoes seguintes, atualizacoes sao identificadas pela
        # data de modificacao do arquivo. Vantagens:
        #   - nao baixa arquivos "somente na nuvem" (OneDrive) so para comparar conteudo;
        #   - sem content_sha256 nao ha dedup por conteudo -- era ele que fazia dois arquivos
        #     de mesmo conteudo em lotes diferentes virarem o MESMO file_id, quebrando o
        #     checkpoint do batch-complete ("arquivo pertence a outro lote").
        # Classificacao:
        #   - fora do baseline               -> novo
        #   - mtime > last_ts (ou sem mtime) -> atualizado
        #   - mtime <= last_ts               -> inalterado (ignora, salvo Execucao Completa)
        #   - baseline sem last_ts           -> assume inalterado (sem referencia p/ comparar)
        unchanged = False
        prior_known = prior_entry is not None
        if prior_known:
            last_ts = prior_entry.get("last_ts")
            if last_ts is None:
                unchanged = True
            else:
                try:
                    file_mtime = source.stat().st_mtime
                except OSError:
                    file_mtime = None  # sem mtime confiavel -> trata como modificado (reenvia)
                if file_mtime is not None and file_mtime <= last_ts:
                    unchanged = True

        if unchanged and not full_execution:
            skipped_unchanged.append(str(source))
            continue

        classification = "audit_duplicate" if unchanged else ("updated" if prior_known else "new")
        classifications[classification] += 1
        selected_files.append(source)
        source_metadata[source_key] = {"content_sha256": None, "classification": classification}
    scan_stats.update(
        {
            "full_execution": full_execution,
            "selected_files": len(selected_files),
            "skipped_unchanged_count": len(skipped_unchanged),
            "skipped_unchanged_files": skipped_unchanged[:20],
            "hash_failed_count": len(hash_failures),
            "hash_failed_files": hash_failures[:20],
            "classifications": classifications,
        }
    )
    update_task_payload(session, task_id, {"scan_stats": scan_stats, "folder_path": normalized_folder})
    if not candidate_files:
        message = no_files_message(scan_stats)
        log("warning", message, automation_id=automation_id, metadata={"folder_path": normalized_folder, **scan_stats})
        return payload, {"status": "no_files", "message": message, "scan_stats": scan_stats}
    if not selected_files and hash_failures:
        message = "Nenhum arquivo pode ser preparado porque a assinatura de conteudo falhou."
        log("error", message, automation_id=automation_id, metadata=local_report_metadata("file_signature_failed", {"folder_path": normalized_folder, **scan_stats}))
        return payload, {"status": "file_signature_failed", "message": message, "scan_stats": scan_stats}
    if not selected_files:
        message = "Nenhum arquivo novo ou atualizado encontrado; arquivos sem alteracao foram ignorados."
        log("info", message, automation_id=automation_id, metadata={"folder_path": normalized_folder, **scan_stats})
        return payload, {"status": "no_changes", "message": message, "scan_stats": scan_stats}

    staging_batch_size = resolve_batch_size(payload)
    staged_files, copy_stats = copy_files_to_staging(
        automation_id=int(automation_id or 0),
        automation_name=payload.get("automation_name"),
        source_files=selected_files,
        batch_size=staging_batch_size,
        temp_folder_path=payload.get("temp_folder_path"),
        log=stage_log,
    )
    files: list[dict[str, Any]] = []
    for staged in staged_files:
        source_path = staged["source_path"]
        staged_path = staged["staged_path"]
        tracked = source_metadata.get(normalized_source_key(source_path), {})
        classification = tracked.get("classification", "new")
        file_payload = {
            "file_name": staged["file_name"],
            "original_path": str(source_path),
            "temp_path": str(staged_path),
            "extension": staged["extension"],
            "size_bytes": staged["size_bytes"],
            "content_sha256": tracked.get("content_sha256"),
            "detection_source": FOLDER_DETECTION_SOURCE,
            "detection_task_id": task_id,
            "detection_classification": classification,
            "workspace_id": workspace_id,
            "automation_id": automation_id,
            "status": "pending",
            "playground_status": "Pending",
            "max_attempts": payload.get("max_retries") or payload.get("max_attempts") or 3,
        }
        db_file = resolve_registered_file(session, register_file(session, file_payload), file_payload)
        file_item = {
            "file_id": db_file.get("id"),
            "file_name": db_file.get("file_name") or staged["file_name"],
            "path": db_file.get("temp_path") or str(staged_path),
            "temp_path": db_file.get("temp_path") or str(staged_path),
            "original_path": db_file.get("original_path") or str(source_path),
            "attempts": db_file.get("attempts") or 0,
            "content_sha256": db_file.get("content_sha256") or tracked.get("content_sha256"),
            "classification": classification,
            "batch_number": staged["batch_number"],
            "batch_folder_path": staged["batch_folder_path"],
        }
        files.append(file_item)
        event_message = {
            "new": "Arquivo novo registrado para upload",
            "updated": "Arquivo atualizado registrado para upload",
            "audit_duplicate": "Arquivo sem alteracao incluido pela Execucao completa",
        }.get(classification, "Arquivo registrado para upload")
        log(
            "info",
            f"{event_message}: {file_item['file_name']}",
            file_id=file_item.get("file_id"),
            automation_id=automation_id,
            metadata={
                "temp_path": file_item.get("temp_path"),
                "original_path": file_item.get("original_path"),
                "content_sha256": file_item.get("content_sha256"),
                "classification": classification,
                "full_execution": full_execution,
                "batch_number": file_item.get("batch_number"),
                "batch_folder_path": file_item.get("batch_folder_path"),
            },
        )

    scan_stats["matched_files"] = len(files)
    scan_stats.update(copy_stats)
    if not files:
        message = no_files_copied_message(copy_stats, scan_stats)
        log("error", message, automation_id=automation_id, metadata=local_report_metadata("no_files_copied", {"folder_path": normalized_folder, **scan_stats}))
        return payload, {"status": "no_files_copied", "message": message, "scan_stats": scan_stats, "copy_stats": copy_stats}

    prepared_payload = {
        **payload,
        "files": files,
        "batch_size": copy_stats.get("batch_size") or staging_batch_size,
        "temp_folder_path": copy_stats.get("staging_dir") or payload.get("temp_folder_path"),
        "scan_stats": scan_stats,
        "copy_stats": copy_stats,
    }
    update_task_payload(
        session,
        task_id,
        {
            "files": files,
            "batch_size": prepared_payload.get("batch_size"),
            "temp_folder_path": prepared_payload.get("temp_folder_path"),
            "scan_stats": scan_stats,
            "copy_stats": copy_stats,
        },
    )
    log(
        "info",
        "Preparacao de arquivos concluida; iniciando automacao web.",
        automation_id=automation_id,
        metadata={"files": len(files), "batch_size": prepared_payload.get("batch_size"), "batch_count": copy_stats.get("batch_count")},
    )
    return prepared_payload, None


def process_connect(session: requests.Session, task: dict[str, Any], payload: dict[str, Any], user_id: Optional[int], log) -> None:
    task_id = task["id"]
    # Tarefa 'rapida' sem automation_id: usa o checker que tambem detecta cancelamento da propria
    # task, para o botao "parar" interromper um login manual em andamento.
    should_continue = task_stop_checker(session, task_id, payload.get("automation_id"), log)
    result = connect_playground_session(
        task_id=task_id, user_id=user_id, payload=payload, log=log, should_continue=should_continue
    )
    complete_task(
        session,
        task_id,
        {
            "connected": result.connected,
            "already_connected": result.already_connected,
            "session_path": result.session_path,
        },
        {"user_id": user_id, "playground_session_path": result.session_path},
    )


def process_workspace_create(session: requests.Session, task: dict[str, Any], payload: dict[str, Any], user_id: Optional[int], log) -> None:
    should_continue = task_stop_checker(session, task["id"], payload.get("automation_id"), log)
    result = create_playground_workspace(
        task_id=task["id"], user_id=user_id, payload=payload, log=log, should_continue=should_continue
    )
    complete_task(session, task["id"], result)


def process_add_user(session: requests.Session, task: dict[str, Any], payload: dict[str, Any], user_id: Optional[int], log) -> None:
    should_continue = task_stop_checker(session, task["id"], payload.get("automation_id"), log)
    result = add_playground_user_to_workspace(
        task_id=task["id"], user_id=user_id, payload=payload, log=log, should_continue=should_continue
    )
    complete_task(session, task["id"], result)


def process_upload(session: requests.Session, task: dict[str, Any], payload: dict[str, Any], user_id: Optional[int], log) -> None:
    automation_id = payload.get("automation_id")
    should_continue = stop_checker(session, task["id"], automation_id, log)
    should_continue()
    payload, terminal_result = prepare_folder_upload_payload(session, task, payload, log)
    is_folder_monitoring_cycle = bool(payload.get("folder_path") or payload.get("source_folder_path"))
    if is_folder_monitoring_cycle and should_generate_folder_report(payload, terminal_result):
        request_automatic_folder_report(session, int(task["id"]), automation_id, log)
    if terminal_result:
        status = str(terminal_result.get("status") or "")
        if status in REPORTABLE_TERMINAL_STATUSES:
            update_automation_status(session, automation_id, "failed")
            fail_task(session, task["id"], terminal_result.get("message") or status, terminal_result)
        else:
            update_automation_status(session, automation_id, "completed")
            complete_task(session, task["id"], terminal_result)
        return
    if payload.get("monitor_only"):
        # "Executar apenas monitoramento de pasta": os arquivos ja foram lidos e copiados
        # para a pasta temp por prepare_folder_upload_payload. Encerra aqui, sem abrir a
        # automacao web (sem login/upload no Playground).
        files_count = len(payload.get("files") or [])
        log(
            "info",
            "Execucao apenas de monitoramento: arquivos lidos e copiados para a pasta temp; automacao web nao foi iniciada.",
            automation_id=automation_id,
            metadata={
                "files": files_count,
                "temp_folder_path": payload.get("temp_folder_path"),
                "batch_count": (payload.get("copy_stats") or {}).get("batch_count"),
            },
        )
        update_automation_status(session, automation_id, "completed")
        complete_task(
            session,
            task["id"],
            {
                "status": "monitor_only",
                "message": "Monitoramento de pasta concluido: arquivos copiados para a pasta temp sem abrir a automacao web.",
                "files": payload.get("files") or [],
                "scan_stats": payload.get("scan_stats"),
                "copy_stats": payload.get("copy_stats"),
                "temp_folder_path": payload.get("temp_folder_path"),
            },
        )
        return
    should_continue()
    uploaded_file_ids: set[int] = set()

    def on_batch_uploaded(batch_number: int, batch_folder_path: str | None, uploaded_files: list[dict[str, Any]]) -> None:
        for f in uploaded_files:
            if f.get("file_id"):
                uploaded_file_ids.add(int(f["file_id"]))
        checkpoint_uploaded_batch(
            session,
            int(task["id"]),
            automation_id,
            batch_number,
            batch_folder_path,
            uploaded_files,
            log,
            should_continue=should_continue,
        )

    def on_file_error(file_id: int | None, error_message: str) -> None:
        if file_id:
            update_file(
                session,
                file_id,
                {
                    "status": "error",
                    "playground_status": "Error",
                    "last_error": error_message,
                },
            )

    # A automacao NAO deleta arquivos da pasta temp (staging): a limpeza automatica
    # (shutil.rmtree) foi desativada de proposito, preservando os arquivos copiados para
    # auditoria/reprocessamento. A limpeza, quando necessaria, e feita manualmente.
    try:
        result = upload_files_to_workspace(
            task_id=task["id"],
            user_id=user_id,
            payload=payload,
            log=log,
            should_continue=should_continue,
            on_batch_uploaded=on_batch_uploaded,
            on_file_error=on_file_error,
        )
        should_continue()
        complete_task(session, task["id"], result)
        if payload.get("start_monitoring_after_upload", True) is False:
            log("info", "Upload concluido; monitoramento nao iniciado para upload manual.", automation_id=automation_id)
            return
        log("info", "Upload concluido; monitoramento foi enfileirado por lote confirmado.", automation_id=automation_id)
    except Exception as upload_exc:
        # Login manual necessario em modo headless: NAO marca os arquivos ainda. O sinal precisa
        # subir intacto para process_task reabrir o Chromium visivel e REPETIR a tarefa; marcar
        # aqui deixaria os arquivos como erro/manual_review indevidamente antes do retry.
        if isinstance(upload_exc, PlaygroundLoginRequired):
            raise
        # FIX (MEDIUM): Previne registros zumbis no banco. Se a task falhou, os arquivos ainda
        # "pending" (nao enviados) nao podem ficar num limbo. Quando a causa e ManualReviewRequired
        # (ex.: checkpoint de um lote nao confirmou -> os lotes POSTERIORES nunca chegaram a ser
        # enviados), o desfecho da task e "revisao manual", nao "falha definitiva": marca esses
        # arquivos como manual_review (nao error), para o status do arquivo bater com o da task.
        # Qualquer outra excecao -> error, como antes.
        is_manual_review = isinstance(upload_exc, ManualReviewRequired)
        for file_item in payload.get("files") or []:
            file_id = file_item.get("file_id")
            if file_id and int(file_id) not in uploaded_file_ids:
                if is_manual_review:
                    update_file(
                        session,
                        file_id,
                        {
                            "status": "manual_review",
                            "playground_status": "Pending",
                            "last_error": f"Upload interrompido para revisao manual: {upload_exc}",
                        },
                    )
                else:
                    on_file_error(
                        file_id,
                        f"Upload abortado devido a falha na task: {upload_exc}",
                    )
        raise


def _resolved_name(item: dict[str, Any]) -> str:
    """Nome do arquivo do item, na MESMA ordem de resolucao que expected_file_name usa no
    monitor (file_name -> name -> basename do caminho), para casar de forma consistente."""
    return str(
        item.get("file_name")
        or item.get("name")
        or Path(str(item.get("path") or item.get("temp_path") or item.get("original_path") or "")).name
    )


def _norm_name(value: str) -> str:
    """Normaliza para comparacao: NFC (acentos com mesma codificacao) + espacos + minusculas."""
    return unicodedata.normalize("NFC", " ".join(str(value or "").split())).lower()


def _item_by_name(files: list[Any], file_name: str, log: Any = None) -> dict[str, Any]:
    """Mapeia o nome lido no monitor de volta ao registro do arquivo de ORIGEM a converter.

    Casamento em camadas, para SEMPRE achar a origem correta sem nunca pegar a errada:
      1. nome EXATO (file_name/name/basename), normalizado NFC + minusculas — alinhado ao
         expected_file_name do monitor (inclui o fallback por 'name', que faltava aqui);
      2. por STEM (sem extensao) APENAS se houver um UNICO candidato (cobre a extensao exibida
         diferir da de origem, ex.: .docx <-> .pdf), sem ambiguidade.
    Sem match, devolve um stub sem caminho -> o chamador trata como revisao manual (nunca
    converte/reenvia o arquivo errado)."""
    dict_items = [item for item in files if isinstance(item, dict)]
    target = _norm_name(file_name)
    for item in dict_items:
        if _norm_name(_resolved_name(item)) == target:
            return item
    target_stem = _norm_name(Path(file_name).stem)
    if target_stem:
        stem_matches = [item for item in dict_items if _norm_name(Path(_resolved_name(item)).stem) == target_stem]
        if len(stem_matches) == 1:
            if log:
                log("info", f"Origem para conversao casada por stem (extensao difere): '{file_name}' -> '{_resolved_name(stem_matches[0])}'")
            return stem_matches[0]
        if len(stem_matches) > 1 and log:
            log("warning", f"Multiplos arquivos com o mesmo stem de '{file_name}'; sem match exato, nao da para desambiguar a origem.")
    if log:
        log("warning", f"Origem nao encontrada para '{file_name}'; sera tratado como revisao manual (sem conversao).")
    return {"file_name": file_name}


def _status_for_name(result: dict[str, Any], file_name: str) -> str:
    status_data = (result.get("statuses") or {}).get(file_name) or {}
    return str(status_data.get("status") or "Unknown")


def _pdf_dir_for_reprocess(
    folder_path: Optional[str],
    fallback_source: Optional[str] = None,
    temp_folder_path: Optional[str] = None,
    run_token: Optional[str] = None,
) -> Optional[str]:
    """Pasta 'PDF' (FORA do temp) onde os arquivos sao convertidos e mantidos para reenvio.

    Prioridade: pasta monitorada (folder_path)/PDF -> parent do arquivo de origem real/PDF
    -> (ultimo recurso) temp_folder_path/PDF. Mantem os PDFs fora do temp e por automacao.

    'run_token' (ex.: id da task de reprocesso) cria uma subpasta unica por execucao
    (PDF/{run_token}), para que reprocessamentos concorrentes da MESMA automacao nao misturem
    arquivos na mesma pasta -- diferente do _pdf_dir_for_resend, que ja herda um staging_dir
    timestamped e por isso e unico "de graca". Preserva a rastreabilidade de auditoria.
    """
    base: Optional[str] = None
    if folder_path:
        base = normalize_folder_path(folder_path)
    if not base and fallback_source:
        base = str(Path(str(fallback_source)).parent)
    if not base and temp_folder_path:
        base = temp_folder_path
    if not base:
        return None
    pdf_base = Path(base) / "PDF"
    return str(pdf_base / str(run_token)) if run_token else str(pdf_base)


def _pdf_dir_for_resend(payload: dict[str, Any], files: list[Any], to_resend_names: list[str]) -> Optional[str]:
    """Pasta 'PDF' DENTRO da pasta de monitoramento deste ciclo, junto com os lotes.

    O monitoramento herda 'temp_folder_path' = diretorio de staging do ciclo (o que contem as
    subpastas lote_NNN). Mantemos a copia dos arquivos em error/processing e seus PDFs em
    '{staging}/PDF', ao lado dos lotes. Fallbacks robustos: derivar do proprio arquivo (parent
    do lote = staging) ou, em ultimo caso, a pasta monitorada/PDF.
    """
    staging_run_dir = normalize_folder_path(payload.get("temp_folder_path"))
    if staging_run_dir:
        return str(Path(staging_run_dir) / "PDF")
    # Fallback: deriva o diretorio de staging do caminho temporario de um arquivo
    # (.../staging/lote_NNN/arquivo -> .../staging).
    for file_name in to_resend_names:
        item = _item_by_name(files, file_name)
        staged = item.get("temp_path") or item.get("path")
        if staged:
            lote_dir = Path(str(staged)).parent
            run_dir = lote_dir.parent if lote_dir.name.lower().startswith("lote_") else lote_dir
            return str(run_dir / "PDF")
    # Ultimo recurso: pasta monitorada/PDF (comportamento anterior).
    return _pdf_dir_for_reprocess(
        payload.get("folder_path") or payload.get("source_folder_path"),
        None,
        payload.get("temp_folder_path"),
    )


def _build_resend_batch(
    session: requests.Session,
    items: list[dict[str, Any]],
    pdf_dir: Optional[str],
    log,
    automation_id: Optional[Any] = None,
    should_continue=None,
    batch_size: Optional[int] = None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Converte cada arquivo para a pasta 'PDF' (fora do temp) e monta o reenvio EM LOTES.

    Assim como o upload normal, os PDFs sao divididos em lotes de 'batch_size' (default
    UPLOAD_BATCH_SIZE), cada lote em sua subpasta 'lote_NNN' dentro da pasta PDF. Como cada item
    recebe um 'batch_folder_path' distinto por lote, o batches_for_upload agrupa por pasta e o
    upload envia/confirma um lote de cada vez (checkpoint por lote), em vez de um unico lote
    gigante. Deixa SOMENTE o PDF convertido na pasta do lote; falha de um arquivo nao derruba os
    demais: ele vira manual_review e o lote segue. Retorna (resend_files, resent_names, failed).
    """
    size = resolve_batch_size(default=batch_size)
    # Base da pasta PDF: usa pdf_dir; se ausente, deriva do primeiro item com origem real
    # (pasta monitorada, nunca o temp). As subpastas 'lote_NNN' ficam dentro dela.
    base_pdf_dir = pdf_dir
    if not base_pdf_dir:
        for candidate in items:
            src = candidate.get("original_path") or candidate.get("temp_path") or candidate.get("path")
            if src:
                base_pdf_dir = str(Path(str(src)).parent / "PDF")
                break
    resend_files: list[dict[str, Any]] = []
    resent_names: list[str] = []
    conversion_failed: list[str] = []
    for batch_index, chunk in enumerate(
        (items[i:i + size] for i in range(0, len(items), size)), start=1
    ):
        # Cada lote vai para 'lote_NNN' (ao lado dos lotes do upload normal); o batch_folder_path
        # distinto e o que faz o upload tratar cada grupo como um lote separado (batches_for_upload).
        batch_dir = str(Path(base_pdf_dir) / f"lote_{batch_index:03d}") if base_pdf_dir else None
        for item in chunk:
            if should_continue:
                should_continue()
            file_id = item.get("file_id") or item.get("id")
            source = item.get("temp_path") or item.get("path") or item.get("original_path")
            name = item.get("resend_name") or item.get("file_name") or (Path(str(source)).name if source else str(file_id))
            if not source:
                update_file(session, file_id, {"status": "manual_review", "last_error": "Sem caminho de origem para reenvio."})
                conversion_failed.append(name)
                continue
            # Pasta do lote baseada na pasta monitorada (original_path), nunca no temp.
            target_pdf_dir = batch_dir or str(
                Path(str(item.get("original_path") or source)).parent / "PDF" / f"lote_{batch_index:03d}"
            )
            try:
                pdf_path = convert_to_pdf_in_folder(str(source), target_pdf_dir, log)
            except Exception as exc:
                update_file(session, file_id, {"status": "manual_review", "last_error": f"Falha na conversao PDF para reenvio: {exc}"})
                log("warning", f"Falha ao converter para PDF (reenvio): {name}: {exc}", file_id=file_id, automation_id=automation_id)
                conversion_failed.append(name)
                continue
            update_file(
                session,
                file_id,
                # suppress_retry_task: o reenvio deste lote ja e orquestrado aqui (uma task de
                # upload em lote no chamador); sem esta flag, o PUT a pending_retry dispararia
                # um convert_and_retry_file por arquivo (1-a-1) em paralelo -> PDF em duplicidade.
                {"pdf_path": pdf_path, "converted_to_pdf": True, "status": "pending_retry",
                 "playground_status": "Pending", "last_error": None, "suppress_retry_task": True},
            )
            resent_names.append(name)
            resend_files.append(
                {
                    "file_id": file_id,
                    "file_name": Path(pdf_path).name,
                    # Nome original (pre-conversao) para correlacao por nome no backend, ja que
                    # 'file_name' agora e o do PDF. Lookup primario continua sendo por file_id.
                    "original_file_name": item.get("file_name") or name,
                    "path": pdf_path,
                    "temp_path": pdf_path,
                    "original_path": item.get("original_path") or source,
                    "batch_number": batch_index,
                    "batch_folder_path": target_pdf_dir,
                    "attempts": int(item.get("attempts") or 0) + 1,
                }
            )
    return resend_files, resent_names, conversion_failed


def process_monitor(session: requests.Session, task: dict[str, Any], payload: dict[str, Any], user_id: Optional[int], log) -> None:
    automation_id = payload.get("automation_id")
    should_continue = stop_checker(session, task["id"], automation_id, log)
    should_continue()
    if task.get("created_at"):
        payload["task_created_at"] = task["created_at"]
    result = monitor_workspace_files_status(task_id=task["id"], user_id=user_id, payload=payload, log=log, should_continue=should_continue)
    should_continue()
    files = payload.get("files") or []

    ready_names = list(result.get("ready") or [])
    manual_review_names = list(result.get("manual_review") or [])
    to_resend_names = list(result.get("to_resend") or [])

    for file_name in ready_names:
        should_continue()
        item = _item_by_name(files, file_name)
        update_file(session, item.get("file_id") or item.get("id"), {"status": "ready", "playground_status": "Ready"})

    for file_name in manual_review_names:
        should_continue()
        item = _item_by_name(files, file_name)
        workspace_status = _status_for_name(result, file_name)
        update_file(
            session,
            item.get("file_id") or item.get("id"),
            {
                "status": "manual_review",
                "playground_status": workspace_status,
                "last_error": f"Workspace retornou {workspace_status}; acao manual necessaria.",
            },
        )

    # Converte os nao-Ready (ja deletados na web, ou ausentes) para PDF na pasta 'PDF'
    # (FORA do temp) e reenvia em UMA unica task, sem monitorar novamente.
    pdf_dir = _pdf_dir_for_resend(payload, files, to_resend_names)
    resend_batch_size = resolve_batch_size(payload)
    items = [{**_item_by_name(files, file_name, log), "resend_name": file_name} for file_name in to_resend_names]
    resend_files, resent_names, conversion_failed = _build_resend_batch(
        session, items, pdf_dir, log, automation_id=automation_id, should_continue=should_continue, batch_size=resend_batch_size
    )

    for file_name in conversion_failed:
        if file_name not in manual_review_names:
            manual_review_names.append(file_name)

    resend_task_id = None
    if resend_files:
        resend_payload = {
            **payload,
            "user_id": user_id,
            "files": resend_files,
            # Reenvio agora vai EM LOTES (lote_NNN); mantem o mesmo tamanho de lote do upload.
            "batch_size": resend_batch_size,
            "temp_folder_path": pdf_dir or payload.get("temp_folder_path"),
            # Reenvio NAO deve disparar novo monitoramento.
            "start_monitoring_after_upload": False,
            "monitoring_timeout_minutes": 0,
        }
        # Remove tambem full_execution: herdado via {**payload}, poderia (com automation_id)
        # fazer o backend reabrir monitor para todos os arquivos da automacao no complete.
        for key in ("completed_batches", "scan_stats", "copy_stats", "full_execution"):
            resend_payload.pop(key, None)
        resend_task_id = create_agent_task(
            session,
            "upload_files_to_workspace",
            resend_payload,
            payload.get("max_retries") or payload.get("max_attempts") or 3,
        )
        log(
            "info",
            f"Reenvio (PDF) enfileirado em lotes, sem novo monitoramento: task {resend_task_id}",
            automation_id=automation_id,
            metadata={
                "files": [item["file_name"] for item in resend_files],
                "batch_count": len({item.get("batch_folder_path") for item in resend_files}),
                "batch_size": resend_batch_size,
            },
        )

    # Alinha o resultado com o que o backend (update_files_from_result) usa para gravar status:
    # os reenviados ficam como pending_retry; Pending + falhas de delecao/conversao como manual_review.
    result["retry"] = resent_names
    result["manual_review"] = manual_review_names
    result["resent"] = [item["file_name"] for item in resend_files]
    result["resend_task_id"] = resend_task_id
    if manual_review_names and not resend_files:
        result["status"] = "manual_review"
        manual_review_task(session, task["id"], "Monitoramento terminou com arquivos em revisao manual.", result)
    else:
        complete_task(session, task["id"], result)


def process_convert_retry(session: requests.Session, task: dict[str, Any], payload: dict[str, Any], user_id: Optional[int], log) -> None:
    task_id = task["id"]
    automation_id = payload.get("automation_id")
    should_continue = stop_checker(session, task_id, automation_id, log)
    should_continue()
    max_attempts = int(payload.get("max_attempts") or payload.get("max_retries") or 3)

    # Aceita LOTE (payload["files"]) ou payload legado de 1 arquivo (file_id no topo).
    raw_files = payload.get("files")
    if raw_files:
        items = [dict(item) for item in raw_files]
    else:
        items = [
            {
                "file_id": payload.get("file_id"),
                "original_path": payload.get("original_path"),
                "temp_path": payload.get("temp_path") or payload.get("original_path"),
                "attempts": int(payload.get("attempts") or 0),
            }
        ]

    # Respeita o limite de tentativas e a existencia de origem (excedentes -> manual_review).
    pending_items: list[dict[str, Any]] = []
    for item in items:
        item_source = item.get("temp_path") or item.get("path") or item.get("original_path")
        if int(item.get("attempts") or 0) >= max_attempts:
            update_file(session, item.get("file_id"), {"status": "manual_review", "playground_status": payload.get("playground_status"), "last_error": "Maximo de tentativas atingido."})
        elif not item_source:
            update_file(session, item.get("file_id"), {"status": "manual_review", "last_error": "Payload sem temp_path/original_path."})
        else:
            pending_items.append(item)

    if not pending_items:
        raise ManualReviewRequired("Nenhum arquivo elegivel para reenvio (tentativas esgotadas ou sem origem).")

    # Pasta PDF FORA do temp (pasta monitorada); converte e monta UM unico lote.
    fallback_source = next(
        (it.get("original_path") or it.get("temp_path") or it.get("path") for it in pending_items if (it.get("original_path") or it.get("temp_path") or it.get("path"))),
        None,
    )
    pdf_dir = _pdf_dir_for_reprocess(
        payload.get("folder_path") or payload.get("source_folder_path"),
        fallback_source,
        payload.get("temp_folder_path"),
        run_token=f"reprocess_{task_id}",
    )
    resend_batch_size = resolve_batch_size(payload)
    resend_files, resent_names, conversion_failed = _build_resend_batch(
        session, pending_items, pdf_dir, log, automation_id=automation_id, should_continue=should_continue, batch_size=resend_batch_size
    )
    if not resend_files:
        raise ManualReviewRequired("Conversao para PDF falhou em todos os arquivos do reenvio.")

    upload_payload = {
        **payload,
        "user_id": user_id,
        "files": resend_files,
        # Reenvio agora vai EM LOTES (lote_NNN); mantem o mesmo tamanho de lote do upload.
        "batch_size": resend_batch_size,
        "temp_folder_path": pdf_dir or payload.get("temp_folder_path"),
        # Reenvio NAO deve disparar novo monitoramento.
        "start_monitoring_after_upload": False,
        "monitoring_timeout_minutes": 0,
    }
    for key in ("completed_batches", "scan_stats", "copy_stats", "file_id", "attempts", "full_execution"):
        upload_payload.pop(key, None)
    should_continue()
    upload_task_id = create_agent_task(session, "upload_files_to_workspace", upload_payload, max_attempts)
    result = {
        "upload_task_id": upload_task_id,
        "resent": [item["file_name"] for item in resend_files],
        "conversion_failed": conversion_failed,
    }
    resend_batch_count = len({item.get("batch_folder_path") for item in resend_files})
    log(
        "info",
        f"Reenvio (PDF) enfileirado em {resend_batch_count} lote(s): task {upload_task_id}",
        automation_id=automation_id,
        metadata={"files": [item["file_name"] for item in resend_files], "batch_count": resend_batch_count, "batch_size": resend_batch_size},
    )
    complete_task(session, task_id, result)


def process_teams_delivery(
    session: requests.Session,
    task: dict[str, Any],
    payload: dict[str, Any],
    user_id: Optional[int],
    log,
) -> None:
    task_id = task["id"]
    report_id = payload.get("report_id")
    if not report_id:
        raise ValueError("deliver_report_teams_playwright exige 'report_id' no payload.")
    if not user_id:
        raise ValueError("deliver_report_teams_playwright exige um 'user_id' associado.")
    
    result = deliver_report_teams_playwright(
        report_id=report_id,
        payload=payload,
        log=log,
        task_id=task_id,
        user_id=user_id
    )
    complete_task(session, task_id, result)


def process_png_teams_delivery(
    session: requests.Session,
    task: dict[str, Any],
    payload: dict[str, Any],
    user_id: Optional[int],
    log,
) -> None:
    """Task da automacao 'PNG -> Teams' (ver app/services/teams_png_watch.py): envia um
    arquivo avulso (payload['file_path']) diretamente para um chat do Teams, sem vinculo com
    um report_id do HUB. Apos o envio confirmado, marca o arquivo (por sha256) como enviado
    para nao ser reenviado na proxima checagem de pasta."""
    task_id = task["id"]
    if not user_id:
        raise ValueError("deliver_png_teams_playwright exige um 'user_id' associado.")

    result = deliver_file_teams_playwright(
        payload=payload,
        log=log,
        task_id=task_id,
        user_id=user_id,
    )

    file_sha256_value = payload.get("file_sha256")
    if file_sha256_value:
        teams_png_watch.mark_png_sent(file_sha256_value, Path(str(payload.get("file_path"))).name)

    complete_task(session, task_id, result)


def _dispatch_task_body(
    session: requests.Session,
    task: dict[str, Any],
    payload: dict[str, Any],
    user_id: Optional[int],
    log,
    task_type: Optional[str],
) -> None:
    """Roteia a task para o process_* correspondente. Isolado do process_task para permitir o
    retry headed (repetir o corpo com payload {headless: False}) sem duplicar o if/elif."""
    if task_type == "connect_playground_session":
        process_connect(session, task, payload, user_id, log)
    elif task_type == "create_playground_workspace":
        process_workspace_create(session, task, payload, user_id, log)
    elif task_type == "add_playground_user_to_workspace":
        process_add_user(session, task, payload, user_id, log)
    elif task_type == "upload_files_to_workspace":
        process_upload(session, task, payload, user_id, log)
    elif task_type == "monitor_workspace_files_status":
        process_monitor(session, task, payload, user_id, log)
    elif task_type == "convert_and_retry_file":
        process_convert_retry(session, task, payload, user_id, log)
    elif task_type == "deliver_report_teams_playwright":
        process_teams_delivery(session, task, payload, user_id, log)
    elif task_type == "deliver_png_teams_playwright":
        process_png_teams_delivery(session, task, payload, user_id, log)


def process_task(session: requests.Session, task: dict[str, Any], agent_id: Optional[int]) -> None:
    task_id = task["id"]
    task_type = task.get("task_type")
    payload = parse_payload(task)
    user_id = resolve_user_id(task, payload)
    log = task_logger(session, task_id, payload.get("automation_id"))
    if task_type not in OFFICIAL_TASK_TYPES:
        fail_task(session, task_id, f"Unknown task type: {task_type}")
        return
    if task_type in PLAYWRIGHT_TASK_TYPES and not user_id:
        message = "Task sem usuario associado; sessao default_user bloqueada para preservar login por usuario."
        log("error", message, metadata={"task_type": task_type, "requires_user_id": True})
        fail_task(session, task_id, message, {"task_type": task_type, "requires_user_id": True})
        return
    if user_id:
        log("info", f"Sessao Playwright vinculada ao usuario {user_id}.", metadata={"session_path": str(session_dir_for_user(user_id))})

    try:
        post_json(session, f"/api/agents/tasks/{task_id}/start", {"agent_id": agent_id})
        try:
            _dispatch_task_body(session, task, payload, user_id, log, task_type)
        except (PlaygroundLoginRequired, TeamsLoginRequired):
            if not payload.get("headless"):
                raise  # ja visivel e login nao concluido -> trata como antes (falha)
            log(
                "warning",
                "Login necessario no servico e o navegador estava em modo headless. Reabrindo o Chromium de "
                "forma VISIVEL para login manual e repetindo a tarefa (a tarefa NAO sera finalizada).",
            )
            payload = {**payload, "headless": False}
            _dispatch_task_body(session, task, payload, user_id, log, task_type)
        log("info", "Task finalizada pelo agente.")
    except AutomationStopped as exc:
        message = str(exc) or "Automacao parada pelo usuario."
        log("warning", message)
        try:
            cancel_task(session, task_id, message)
        except Exception as cancel_exc:
            print(f"[ERROR] Falha ao cancelar task {task_id}: {cancel_exc}", flush=True)
    except ManualReviewRequired as exc:
        message = str(exc) or exc.__class__.__name__
        log("warning", message)
        manual_review_task(session, task_id, message, {"task_type": task_type})
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        log("error", message)
        try:
            fail_task(session, task_id, message, {"task_type": task_type})
        except Exception as fail_exc:
            print(f"[ERROR] Falha ao marcar task {task_id} como failed: {fail_exc}", flush=True)


def run_agent() -> None:
    print("Starting Local Agent...", flush=True)
    sessions: dict[str, requests.Session] = {}
    agent_ids: dict[str, Optional[int]] = {}
    connected = False
    heartbeat_payload = {"name": AGENT_NAME, "machine_name": os.getenv("COMPUTERNAME", "DEV-PC"), "version": "1.0-playwright"}

    for environment in SUPPORTED_ENVIRONMENTS:
        session = requests.Session()
        session.headers.update({"X-Agent-Token": settings.AGENT_SHARED_TOKEN, "X-App-Environment": environment})
        sessions[environment] = session
        agent_ids[environment] = None
        try:
            with environment_scope(environment):
                heartbeat = post_json(session, "/api/agents/heartbeat", heartbeat_payload)
            agent_ids[environment] = heartbeat.get("agent_id")
            connected = True
            print(f"Heartbeat registered: {environment}.", flush=True)
        except Exception as exc:
            print(f"Could not connect to backend environment {environment}: {exc}", flush=True)
    if not connected:
        return

    try:
        while True:
            for environment in SUPPORTED_ENVIRONMENTS:
                session = sessions[environment]
                try:
                    with environment_scope(environment):
                        heartbeat = post_json(session, "/api/agents/heartbeat", heartbeat_payload)
                        agent_ids[environment] = heartbeat.get("agent_id") or agent_ids[environment]
                        poll = post_json(session, "/api/agents/poll", {"agent_id": agent_ids[environment]})
                        tasks = poll.get("tasks", [])
                        if tasks:
                            print(f"Received {len(tasks)} tasks: {environment}.", flush=True)
                        for task in tasks:
                            print(f"Processing task {task['id']}: {task.get('task_type')} [{environment}]", flush=True)
                            process_task(session, task, agent_ids[environment])
                except Exception as exc:
                    print(f"Error polling {environment}: {exc}", flush=True)

            time.sleep(settings.AGENT_POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("Local Agent stopped by user.", flush=True)


if __name__ == "__main__":
    run_agent()
