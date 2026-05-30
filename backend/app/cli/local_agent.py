from __future__ import annotations

import ast
import hashlib
import json
import os
import time
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
from app.services.playwright.errors import ManualReviewRequired, UnsupportedFormat
from app.services.playwright.browser import session_dir_for_user
from app.services.playwright.playground_login import connect_playground_session
from app.services.playwright.playground_monitor import monitor_workspace_files_status
from app.services.playwright.playground_upload import convert_file_to_pdf, convert_to_pdf_in_folder, upload_files_to_workspace
from app.services.playwright.playground_users import add_playground_user_to_workspace
from app.services.playwright.playground_workspace import create_playground_workspace


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
    response.raise_for_status()
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
                time.sleep(1)
    raise ManualReviewRequired(
        f"Lote {batch_number} pode ter sido enviado ao Playground, mas o checkpoint nao foi persistido; "
        "nenhum lote posterior sera enviado ate revisao."
    ) from last_error


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
        try:
            content_sha256 = file_sha256(source)
        except OSError as exc:
            failure = {"path": str(source), "error": str(exc)}
            hash_failures.append(failure)
            log("error", f"Arquivo nao pode ser assinado para comparacao: {source.name}", automation_id=automation_id, metadata=local_report_metadata("file_signature_failed", failure))
            continue
        source_key = normalized_source_key(source)
        prior_entry = baseline.get(source_key)
        # --- dedup persistente entre execucoes agendadas ---
        # prior_entry e None  -> arquivo nunca processado (new)
        # prior_entry["hashes"] contem o sha256 atual -> conteudo identico (unchanged)
        # prior_entry["hashes"] vazio (registro legado sem sha256) -> fallback por mtime:
        #   se mtime do arquivo no disco <= last_ts do upload anterior, nao houve alteracao
        #   (unchanged); caso contrario, arquivo foi modificado apos o upload (updated).
        unchanged = False
        if prior_entry is not None:
            prior_hashes = prior_entry["hashes"]
            if prior_hashes:
                # Comparacao de conteudo exata (caminho principal)
                unchanged = content_sha256 in prior_hashes
            else:
                # Fallback por mtime para registros legados sem sha256 armazenado
                last_ts = prior_entry.get("last_ts")
                if last_ts is not None:
                    try:
                        file_mtime = source.stat().st_mtime
                        unchanged = file_mtime <= last_ts
                        if not unchanged:
                            log(
                                "info",
                                f"Arquivo modificado apos ultimo upload (mtime fallback): {source.name}",
                                automation_id=automation_id,
                                metadata={
                                    "original_path": str(source),
                                    "file_mtime": file_mtime,
                                    "last_upload_ts": last_ts,
                                },
                            )
                    except OSError:
                        # Nao conseguiu ler mtime; trata como modificado (conservador)
                        unchanged = False
                else:
                    # Sem sha256 e sem timestamp: nao ha como confirmar que e o mesmo
                    # conteudo. Trata como inalterado para evitar reenvio redundante de
                    # registros antigos sem metadados suficientes.
                    unchanged = True
                    log(
                        "info",
                        f"Arquivo com registro anterior sem hash nem timestamp; assumindo inalterado: {source.name}",
                        automation_id=automation_id,
                        metadata={"original_path": str(source), "content_sha256": content_sha256},
                    )
        # ---------------------------------------------------
        if unchanged and not full_execution:
            skipped_unchanged.append(str(source))
            log(
                "info",
                f"Arquivo sem alteracao ignorado: {source.name}",
                automation_id=automation_id,
                metadata={"original_path": str(source), "content_sha256": content_sha256},
            )
            continue
        prior_known = prior_entry is not None
        classification = "audit_duplicate" if unchanged else ("updated" if prior_known else "new")
        classifications[classification] += 1
        selected_files.append(source)
        source_metadata[source_key] = {"content_sha256": content_sha256, "classification": classification}
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

    try:
        staging_batch_size = max(1, int(payload.get("batch_size") or settings.UPLOAD_BATCH_SIZE))
    except (TypeError, ValueError):
        staging_batch_size = max(1, int(settings.UPLOAD_BATCH_SIZE))
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
    result = connect_playground_session(task_id=task_id, user_id=user_id, payload=payload, log=log)
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
    result = create_playground_workspace(task_id=task["id"], user_id=user_id, payload=payload, log=log)
    complete_task(session, task["id"], result)


def process_add_user(session: requests.Session, task: dict[str, Any], payload: dict[str, Any], user_id: Optional[int], log) -> None:
    result = add_playground_user_to_workspace(task_id=task["id"], user_id=user_id, payload=payload, log=log)
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
        # FIX (MEDIUM): Previne registros zumbis no banco. Se a task falhou, marca todos os arquivos
        # que ainda estao em "pending" (nao foram enviados com sucesso) como "error".
        for file_item in payload.get("files") or []:
            file_id = file_item.get("file_id")
            if file_id and int(file_id) not in uploaded_file_ids:
                on_file_error(
                    file_id,
                    f"Upload abortado devido a falha na task: {upload_exc}",
                )
        raise


def _item_by_name(files: list[Any], file_name: str) -> dict[str, Any]:
    for item in files:
        if isinstance(item, dict):
            candidate = item.get("file_name") or Path(str(item.get("path") or item.get("temp_path") or "")).name
            if candidate == file_name:
                return item
    return {"file_name": file_name}


def _status_for_name(result: dict[str, Any], file_name: str) -> str:
    status_data = (result.get("statuses") or {}).get(file_name) or {}
    return str(status_data.get("status") or "Unknown")


def _pdf_dir_for_resend(payload: dict[str, Any], files: list[Any], to_resend_names: list[str]) -> Optional[str]:
    """Pasta 'PDF' dentro do temp (staging) onde os nao-Ready sao recortados e convertidos."""
    base_temp = payload.get("temp_folder_path")
    if not base_temp:
        for file_name in to_resend_names:
            item = _item_by_name(files, file_name)
            candidate = item.get("temp_path") or item.get("path")
            if candidate:
                base_temp = str(Path(candidate).parent)
                break
    return str(Path(base_temp) / "PDF") if base_temp else None


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

    # Converte os nao-Ready (ja deletados na web, ou ausentes) para PDF na pasta 'PDF' do temp
    # e reenvia em UMA unica task, sem monitorar novamente.
    pdf_dir = _pdf_dir_for_resend(payload, files, to_resend_names)
    resend_files: list[dict[str, Any]] = []
    resent_names: list[str] = []
    conversion_failed: list[str] = []
    for file_name in to_resend_names:
        should_continue()
        item = _item_by_name(files, file_name)
        file_id = item.get("file_id") or item.get("id")
        source = item.get("temp_path") or item.get("path") or item.get("original_path")
        if not source:
            update_file(session, file_id, {"status": "manual_review", "last_error": "Sem caminho de origem para reenvio."})
            conversion_failed.append(file_name)
            continue
        target_pdf_dir = pdf_dir or str(Path(str(source)).parent / "PDF")
        try:
            pdf_path = convert_to_pdf_in_folder(str(source), target_pdf_dir, log)
        except Exception as exc:
            update_file(session, file_id, {"status": "manual_review", "last_error": f"Falha na conversao PDF para reenvio: {exc}"})
            log("warning", f"Falha ao converter para PDF (reenvio): {file_name}: {exc}", file_id=file_id, automation_id=automation_id)
            conversion_failed.append(file_name)
            continue
        update_file(
            session,
            file_id,
            {"pdf_path": pdf_path, "converted_to_pdf": True, "status": "pending_retry", "playground_status": "Pending", "last_error": None},
        )
        resent_names.append(file_name)
        resend_files.append(
            {
                "file_id": file_id,
                "file_name": Path(pdf_path).name,
                "path": pdf_path,
                "temp_path": pdf_path,
                "original_path": item.get("original_path") or source,
                "batch_number": 1,
                "batch_folder_path": target_pdf_dir,
                "attempts": int(item.get("attempts") or 0) + 1,
            }
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
            "batch_size": max(1, len(resend_files)),
            "temp_folder_path": pdf_dir or payload.get("temp_folder_path"),
            # Reenvio NAO deve disparar novo monitoramento.
            "start_monitoring_after_upload": False,
            "monitoring_timeout_minutes": 0,
        }
        for key in ("completed_batches", "scan_stats", "copy_stats"):
            resend_payload.pop(key, None)
        resend_task_id = create_agent_task(
            session,
            "upload_files_to_workspace",
            resend_payload,
            payload.get("max_retries") or payload.get("max_attempts") or 3,
        )
        log(
            "info",
            f"Reenvio (PDF) enfileirado sem novo monitoramento: task {resend_task_id}",
            automation_id=automation_id,
            metadata={"files": [item["file_name"] for item in resend_files]},
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
    attempts = int(payload.get("attempts") or 0)
    max_attempts = int(payload.get("max_attempts") or payload.get("max_retries") or 3)
    file_id = payload.get("file_id")
    source = payload.get("temp_path") or payload.get("original_path")
    if not source:
        raise UnsupportedFormat("Payload sem temp_path/original_path.")
    if attempts >= max_attempts:
        update_file(
            session,
            file_id,
            {
                "status": "manual_review",
                "playground_status": payload.get("playground_status"),
                "last_error": "Maximo de tentativas atingido.",
            },
        )
        raise ManualReviewRequired("Maximo de tentativas atingido para reenvio.")

    path = Path(str(source))
    if path.suffix.lower() == ".pdf":
        pdf_path = str(path)
        log("info", "Arquivo ja e PDF; reenvio sem nova conversao.", file_id=file_id, automation_id=payload.get("automation_id"))
    else:
        pdf_path = convert_file_to_pdf(str(path), payload.get("temp_folder_path"), log)

    should_continue()
    next_attempt = attempts + 1
    update_file(
        session,
        file_id,
        {
            "pdf_path": pdf_path,
            "converted_to_pdf": Path(pdf_path).suffix.lower() == ".pdf",
            "attempts": next_attempt,
            "status": "pending_retry",
            "last_error": None,
        },
    )
    upload_payload = {
        **payload,
        "user_id": user_id,
        "files": [
            {
                "file_id": file_id,
                "file_name": Path(pdf_path).name,
                "path": pdf_path,
                "temp_path": pdf_path,
                "original_path": payload.get("original_path") or source,
                "attempts": next_attempt,
            }
        ],
        "batch_size": 1,
        # Reenvio individual (PDF) tambem NAO deve disparar novo monitoramento.
        "start_monitoring_after_upload": False,
        "monitoring_timeout_minutes": 0,
    }
    should_continue()
    upload_task_id = create_agent_task(session, "upload_files_to_workspace", upload_payload, max_attempts)
    result = {"pdf_path": pdf_path, "upload_task_id": upload_task_id, "attempts": next_attempt}
    log("info", f"Reenvio iniciado pela task: {upload_task_id}", file_id=file_id, automation_id=payload.get("automation_id"))
    complete_task(session, task_id, result)


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
