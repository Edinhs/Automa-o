from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from app.core.config import runtime_path, settings
from app.services.playwright.browser import click_first, open_persistent_chromium, page_text, safe_error_screenshot, wait_for_text
from app.services.playwright.errors import (
    ManualReviewRequired,
    PlaywrightAutomationError,
    RecoverableUploadUiError,
    UnsupportedFormat,
    UploadFailed,
)
from app.services.playwright.playground_login import configured_playground_url, ensure_logged_in
from app.services.playwright.playground_workspace import open_workspace
from app.services.playwright.selectors import CHOOSE_FILES_TEXTS, UPLOAD_ACTIVE_TEXTS, UPLOAD_COMPLETE_TEXTS, UPLOAD_FILES_TEXTS, UPLOAD_PROGRESS_TEXTS


SUPPORTED_OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".csv"}
DEFAULT_BROWSER_RESTART_ATTEMPTS = 2
SAME_SESSION_RECOVERY_ATTEMPTS = 2
NEXT_BATCH_WAIT_SECONDS = 5
# Segundos sem o indicador "Uploading Files" necessarios para confirmar a conclusao do
# lote quando o Playground nao exibe um texto explicito de "Upload complete".
UPLOAD_COMPLETE_STABLE_SECONDS = 3


def check_continue(should_continue: Callable[[], bool] | None) -> None:
    if should_continue:
        should_continue()


def chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def batches_for_upload(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    batch_folders: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        folder_path = str(item.get("batch_folder_path") or "").strip()
        if not folder_path:
            return chunked(items, size)
        batch_folders.setdefault(folder_path, []).append(item)
    return list(batch_folders.values())


def normalize_file_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        path = item.get("path") or item.get("temp_path") or item.get("pdf_path") or item.get("original_path")
        normalized = dict(item)
        normalized["path"] = str(path or "").strip()
        return normalized
    return {"path": str(item or "").strip()}


def enabled_upload_button(page):
    for text in UPLOAD_FILES_TEXTS:
        for lookup in [
            lambda text=text: page.get_by_role("button", name=text),
            lambda text=text: page.get_by_text(text, exact=False),
        ]:
            try:
                locator = lookup()
                count = locator.count()
            except Exception:
                continue
            for index in range(count):
                candidate = locator.nth(index) if hasattr(locator, "nth") else (locator.first if index == 0 else locator.last)
                try:
                    if candidate.is_visible(timeout=500) and candidate.is_enabled(timeout=500):
                        return candidate
                except Exception:
                    continue
    return None


def click_upload_files(page, log: Callable) -> None:
    button = enabled_upload_button(page)
    if button is None:
        raise RecoverableUploadUiError("Botao Upload Files habilitado nao encontrado.")
    try:
        button.click(timeout=5000)
    except Exception as exc:
        if final_upload_click_error_is_recoverable(exc):
            raise RecoverableUploadUiError("Botao Upload Files deixou de estar habilitado antes do clique.") from exc
        raise
    log("info", "Upload Files clicado.")


def choose_files(page, paths: list[str], log: Callable) -> None:
    try:
        with page.expect_file_chooser(timeout=5000) as file_chooser_info:
            clicked = click_first(
                [lambda text=text: page.get_by_role("button", name=text) for text in CHOOSE_FILES_TEXTS]
                + [lambda text=text: page.get_by_text(text, exact=False) for text in CHOOSE_FILES_TEXTS],
                timeout_ms=5000,
            )
            if not clicked:
                raise UploadFailed("Choose Files nao encontrado.")
        file_chooser_info.value.set_files(paths)
        log("info", "Arquivos selecionados.")
        return
    except Exception:
        file_input = page.locator('input[type="file"]').first
        if file_input.count():
            file_input.set_input_files(paths, timeout=5000)
            log("info", "Arquivos selecionados via input file.")
            return
        raise


def wait_for_selected_files(page, batch: list[dict[str, Any]], log: Callable, should_continue: Callable[[], bool] | None = None) -> None:
    expected_names = [str(item.get("file_name") or Path(item["path"]).name) for item in batch]
    started_at = time.monotonic()
    deadline = time.monotonic() + 60
    log("info", "Aguardando arquivos carregarem antes do Upload Files final.", metadata={"files": expected_names})
    while time.monotonic() < deadline:
        check_continue(should_continue)
        body = page_text(page).lower()
        found = [name for name in expected_names if name.lower() in body]
        if len(found) == len(expected_names):
            log("info", "Arquivos carregados na tela.", metadata={"files": found})
            return
        if time.monotonic() - started_at >= 5 and final_upload_button_enabled(page):
            log("info", "Botao Upload Files final habilitado apos selecao dos arquivos.", metadata={"loaded": found, "expected": expected_names})
            return
        if found:
            log("info", "Parte dos arquivos ja aparece na tela.", metadata={"loaded": found, "expected": expected_names})
        time.sleep(1)
    log("warning", "Nao foi possivel confirmar todos os nomes na tela; tentando Upload Files final mesmo assim.", metadata={"files": expected_names})


def final_upload_button_enabled(page) -> bool:
    for text in UPLOAD_FILES_TEXTS:
        for locator in [page.get_by_role("button", name=text), page.get_by_text(text, exact=False)]:
            try:
                count = locator.count()
                if count and locator.last.is_visible(timeout=500) and locator.last.is_enabled(timeout=500):
                    return True
            except Exception:
                continue
    return False


def wait_after_upload_message(seconds: int, should_continue: Callable[[], bool] | None = None) -> None:
    deadline = time.monotonic() + max(0, seconds)
    while time.monotonic() < deadline:
        check_continue(should_continue)
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def final_upload_click_error_is_recoverable(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "element is not enabled" in message or ("locator.click" in message and "timeout" in message)


def final_upload_click_failure_message(exc: Exception) -> str:
    message = str(exc or "").lower()
    if "element is not enabled" in message or "not enabled" in message:
        return "Clique no Upload Files final falhou porque o botao esta desabilitado."
    return "Clique no Upload Files final falhou antes do upload iniciar."


def click_final_upload_candidate(locator, log: Callable) -> bool:
    try:
        count = locator.count()
    except Exception:
        return False
    if not count:
        return False

    button = locator.last
    try:
        visible = button.is_visible(timeout=500)
    except Exception:
        visible = False
    if not visible:
        return False

    try:
        enabled = button.is_enabled(timeout=500)
    except Exception:
        enabled = False
    if not enabled:
        message = "Botao final Upload Files encontrado, mas desabilitado."
        log("warning", message)
        raise RecoverableUploadUiError(message)

    try:
        button.click(timeout=5000)
    except Exception as exc:
        if final_upload_click_error_is_recoverable(exc):
            message = final_upload_click_failure_message(exc)
            log("warning", message, metadata={"error": str(exc)})
            raise RecoverableUploadUiError(message) from exc
        raise
    log("info", "Upload Files final clicado.")
    return True


def click_final_upload_with_recovery(page, log: Callable, should_continue: Callable[[], bool] | None = None) -> None:
    last_error = None
    for attempt in range(1, 6):
        check_continue(should_continue)
        try:
            for text in UPLOAD_FILES_TEXTS:
                locator = page.get_by_role("button", name=text)
                if click_final_upload_candidate(locator, log):
                    return
            for text in UPLOAD_FILES_TEXTS:
                locator = page.get_by_text(text, exact=False)
                if click_final_upload_candidate(locator, log):
                    return
            raise RecoverableUploadUiError("Botao final Upload Files nao encontrado.")
        except Exception as exc:
            last_error = exc
            if isinstance(exc, RecoverableUploadUiError) and "desabilitado" in str(exc).lower():
                log("warning", f"Botao final Upload Files desabilitado na tentativa {attempt}.")
            else:
                log("warning", f"Botao final Upload Files nao encontrado na tentativa {attempt}.")
            try:
                page.mouse.wheel(0, 600)
            except Exception:
                pass
            time.sleep(1)
            if attempt == 3:
                try:
                    page.keyboard.press("Escape")
                    time.sleep(1)
                except Exception:
                    pass
            if attempt == 4:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
                except Exception:
                    pass
    if isinstance(last_error, RecoverableUploadUiError):
        raise RecoverableUploadUiError(str(last_error) or "Botao final Upload Files nao encontrado.") from last_error
    raise UploadFailed(str(last_error) if last_error else "Falha ao clicar Upload Files final.")


def browser_restart_attempts(payload: dict[str, Any]) -> int:
    raw = payload.get("max_browser_restarts_on_upload_error")
    if raw in [None, ""]:
        raw = payload.get("browser_restart_attempts")
    if raw in [None, ""]:
        raw = DEFAULT_BROWSER_RESTART_ATTEMPTS
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_BROWSER_RESTART_ATTEMPTS


def close_browser(browser, log: Callable, message: str) -> None:
    if not browser:
        return
    try:
        browser.close()
        log("info", message)
    except Exception as exc:
        log("warning", f"Falha ao fechar navegador: {exc}")


def save_recovery_screenshot(browser, task_id: int, log: Callable) -> bool:
    if not browser or not getattr(browser, "page", None):
        return False
    path = safe_error_screenshot(browser.page, task_id)
    if path:
        log("warning", "Screenshot salvo antes da recuperacao.", metadata={"screenshot_path": str(path)})
        return True
    return False


def open_upload_browser_session(
    task_id: int,
    user_id: int | None,
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    *,
    recovery: bool = False,
):
    check_continue(should_continue)
    browser = None
    try:
        browser = open_persistent_chromium(
            user_id,
            headless=payload.get("headless"),
            browser_channel=payload.get("browser_channel"),
        )
        page = browser.page
        if recovery:
            log("info", "Chromium reiniciado para repetir lote.", metadata={"session_path": str(browser.session_dir)})
        else:
            log("info", "Chromium iniciado.", metadata={"session_path": str(browser.session_dir)})
        check_continue(should_continue)
        page.goto(configured_playground_url(payload), wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        ensure_logged_in(page, payload, log)
        check_continue(should_continue)
        if recovery:
            log("info", "Reabrindo workspace apos reinicio do Chromium.")
        open_workspace(page, workspace_name, log)
        return browser, page
    except Exception:
        if browser and getattr(browser, "page", None):
            safe_error_screenshot(browser.page, task_id, log)
        close_browser(browser, log, "Navegador fechado apos falha ao iniciar sessao.")
        raise


def recover_upload_area_in_same_session(
    page,
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> None:
    check_continue(should_continue)
    log("warning", "Recuperando area de upload na mesma sessao do Chromium.")
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    page.reload(wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
    ensure_logged_in(page, payload, log)
    check_continue(should_continue)
    if enabled_upload_button(page) is not None:
        log("info", "Area de upload recuperada apos recarregar a pagina.")
        return
    open_workspace(page, workspace_name, log, expected_area="upload")
    if enabled_upload_button(page) is None:
        raise RecoverableUploadUiError("Area de upload reaberta, mas nenhum botao Upload Files habilitado foi encontrado.")
    log("info", "Area de upload recuperada apos reabrir o Workspace.")


def upload_batch(page, batch: list[dict[str, Any]], log: Callable, should_continue: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
    paths = [str(Path(item["path"]).resolve()) for item in batch]
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        raise UploadFailed(f"Arquivo(s) nao encontrado(s): {missing}")
    check_continue(should_continue)
    click_upload_files(page, log)
    check_continue(should_continue)
    choose_files(page, paths, log)
    check_continue(should_continue)
    wait_for_selected_files(page, batch, log, should_continue=should_continue)
    click_final_upload_with_recovery(page, log, should_continue=should_continue)

    # --- Fase 1: Aguarda o upload INICIAR (aparecimento do texto ativo) ---
    deadline_start = time.monotonic() + 30
    upload_started = False
    saw_active = False
    while time.monotonic() < deadline_start:
        check_continue(should_continue)
        body = page_text(page).lower()
        if "uploading error" in body or "upload error" in body:
            raise UploadFailed("Uploading error")
        if any(text.lower() in body for text in UPLOAD_ACTIVE_TEXTS):
            upload_started = True
            saw_active = True
            log("info", "Uploading Files detectado; aguardando conclusao.")
            break
        # Tambem aceita conclusao imediata (lotes muito pequenos)
        if any(text.lower() in body for text in UPLOAD_COMPLETE_TEXTS):
            upload_started = True
            saw_active = True
            log("info", "Upload concluido diretamente sem fase ativa detectada.")
            break
        time.sleep(0.5)

    if not upload_started:
        body = page_text(page).lower()
        if "uploading error" in body or "upload error" in body:
            raise UploadFailed("Uploading error")
        raise UploadFailed("Lote nao iniciou o envio no tempo esperado (30s).")

    # --- Fase 2: Aguarda o upload COMPLETAR ---
    # A conclusao do lote e reconhecida por DUAS vias, porque o Playground nem sempre
    # exibe um texto explicito de "Upload complete":
    #   (1) texto de conclusao presente E indicador ativo ausente; ou
    #   (2) o indicador "Uploading Files" apareceu e depois desapareceu de forma estavel
    #       (UPLOAD_COMPLETE_STABLE_SECONDS sem texto ativo), caso comum em que a UI apenas
    #       passa a listar o arquivo sem mostrar mensagem de conclusao.
    deadline_complete = time.monotonic() + 180  # timeout generoso para arquivos grandes
    absent_since: float | None = None
    while time.monotonic() < deadline_complete:
        check_continue(should_continue)
        body = page_text(page).lower()
        if "uploading error" in body or "upload error" in body:
            raise UploadFailed("Uploading error")
        has_active = any(text.lower() in body for text in UPLOAD_ACTIVE_TEXTS)
        has_complete = any(text.lower() in body for text in UPLOAD_COMPLETE_TEXTS)
        if has_active:
            # Ainda enviando (ou proximo arquivo do lote iniciou): reseta a janela de ausencia.
            saw_active = True
            absent_since = None
        elif has_complete:
            log("info", "Upload concluido com sucesso (texto de conclusao detectado).")
            break
        elif saw_active:
            # O indicador de envio apareceu e sumiu; confirma estabilidade antes de concluir
            # para nao finalizar em uma queda momentanea entre arquivos do mesmo lote.
            if absent_since is None:
                absent_since = time.monotonic()
            elif time.monotonic() - absent_since >= UPLOAD_COMPLETE_STABLE_SECONDS:
                log("info", "Upload concluido com sucesso (indicador de envio desapareceu).")
                break
        time.sleep(1.0)
    else:
        body = page_text(page).lower()
        if "uploading error" in body or "upload error" in body:
            raise UploadFailed("Uploading error")
        raise UploadFailed("Nao foi possivel confirmar a conclusao do upload do lote no tempo limite.")

    wait_after_upload_message(NEXT_BATCH_WAIT_SECONDS, should_continue=should_continue)
    log("info", "Espera apos Upload concluida.")
    return [
        {
            **item,
            "file_name": item.get("file_name") or Path(item["path"]).name,
            "uploaded_path": item["path"],
            "status": "uploaded",
        }
        for item in batch
    ]


def upload_files_to_workspace(
    task_id: int,
    user_id: int | None,
    payload: dict[str, Any],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    on_batch_uploaded: Callable[[int, str | None, list[dict[str, Any]]], None] | None = None,
    on_file_error: Callable[[int | None, str], None] | None = None,
) -> dict[str, Any]:
    workspace_name = str(payload.get("workspace_name") or "").strip()
    if not workspace_name:
        raise PlaywrightAutomationError("Payload sem workspace_name.")
    files = [normalize_file_item(item) for item in payload.get("files") or []]
    files = [item for item in files if item.get("path")]
    if not files:
        raise UploadFailed("Payload sem arquivos para upload.")
    batch_size = max(1, int(payload.get("batch_size") or settings.UPLOAD_BATCH_SIZE))
    max_browser_restarts = browser_restart_attempts(payload)
    uploaded: list[dict[str, Any]] = []
    batches = batches_for_upload(files, batch_size)
    staged_batch_folders = [
        str(batch[0].get("batch_folder_path"))
        for batch in batches
        if batch and batch[0].get("batch_folder_path")
    ]

    browser = None
    error_screenshot_saved = False
    try:
        if staged_batch_folders:
            log(
                "info",
                "Subpastas de lote preparadas para envio sequencial.",
                metadata={"batch_count": len(batches), "batch_size": batch_size, "batch_folders": staged_batch_folders},
            )
        browser, page = open_upload_browser_session(task_id, user_id, payload, workspace_name, log, should_continue)
        for index, batch in enumerate(batches, start=1):
            restart_attempt = 0
            same_session_recovery_attempt = 0
            batch_folder_path = batch[0].get("batch_folder_path") if batch else None
            batch_number = int(batch[0].get("batch_number") or index) if batch else index
            while True:
                check_continue(should_continue)
                log(
                    "info",
                    f"Lote iniciado: {batch_number}",
                    metadata={
                        "batch": batch_number,
                        "count": len(batch),
                        "batch_folder_path": batch_folder_path,
                        "browser_restart_attempt": restart_attempt,
                        "same_session_recovery_attempt": same_session_recovery_attempt,
                    },
                )
                try:
                    if index > 1 and restart_attempt == 0 and same_session_recovery_attempt == 0:
                        log("info", "Limpando estado do lote anterior antes do proximo envio.", metadata={"batch": batch_number})
                        recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
                    batch_result = upload_batch(page, batch, log, should_continue=should_continue)
                except RecoverableUploadUiError as exc:
                    error_screenshot_saved = save_recovery_screenshot(browser, task_id, log)
                    if same_session_recovery_attempt < SAME_SESSION_RECOVERY_ATTEMPTS:
                        same_session_recovery_attempt += 1
                        log(
                            "warning",
                            "Erro recuperavel no Upload Files; repetindo lote na mesma sessao do Chromium.",
                            metadata={
                                "batch": batch_number,
                                "attempt": same_session_recovery_attempt,
                                "max_attempts": SAME_SESSION_RECOVERY_ATTEMPTS,
                                "error": str(exc),
                            },
                        )
                        try:
                            recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
                        except Exception as recovery_exc:
                            log(
                                "warning",
                                "Recuperacao da area de upload na mesma sessao nao concluiu.",
                                metadata={"batch": batch_number, "error": str(recovery_exc)},
                            )
                        continue
                    if restart_attempt >= max_browser_restarts:
                        log(
                            "error",
                            "Limite de reinicios do Chromium atingido; finalizando com falha.",
                            metadata={
                                "batch": batch_number,
                                "attempts": restart_attempt,
                                "max_attempts": max_browser_restarts,
                                "same_session_attempts": same_session_recovery_attempt,
                                "error": str(exc),
                            },
                        )
                        raise
                    restart_attempt += 1
                    log(
                        "warning",
                        "Recuperacao na mesma sessao esgotada; reiniciando Chromium.",
                        metadata={
                            "batch": batch_number,
                            "attempt": restart_attempt,
                            "max_attempts": max_browser_restarts,
                            "same_session_attempts": same_session_recovery_attempt,
                            "error": str(exc),
                        },
                    )
                    close_browser(browser, log, "Navegador fechado para recuperacao.")
                    browser = None
                    browser, page = open_upload_browser_session(task_id, user_id, payload, workspace_name, log, should_continue, recovery=True)
                    same_session_recovery_attempt = 0
                    log("info", "Repetindo lote apos reinicio do Chromium.", metadata={"batch": batch_number, "attempt": restart_attempt})
                    continue
                except UploadFailed as exc:
                    if "uploading error" in str(exc).lower():
                        if not batch:
                            raise

                        # Captura screenshot para diagnostico antes de qualquer operacao
                        error_screenshot_saved = save_recovery_screenshot(browser, task_id, log)

                        log(
                            "warning",
                            f"Uploading error detectado na pagina do Playground. Isolando arquivos do lote {batch_number} um a um para identificar o corrompido.",
                            metadata={"batch": batch_number, "files": [i.get("file_name") for i in batch]},
                        )

                        # FIX #4 (HIGH): Estrategia de isolamento um a um.
                        # Em vez de assumir cegamente que o ultimo arquivo e o culpado (o que destruiria
                        # arquivos saudaveis), reenviamos cada arquivo individualmente para identificar
                        # com precisao qual causa o erro.
                        corrupted_items: list[dict[str, Any]] = []
                        healthy_results: list[dict[str, Any]] = []

                        # FIX #2 (CRITICAL): Recuperar a sessao ANTES de qualquer operacao de I/O
                        # para liberar os locks de arquivo do Windows que o Chromium mantem ativos.
                        try:
                            recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
                        except Exception as recovery_exc:
                            log(
                                "warning",
                                "Recuperacao da area de upload falhou antes do isolamento individual.",
                                metadata={"error": str(recovery_exc)},
                            )

                        for solo_item in list(batch):
                            check_continue(should_continue)
                            try:
                                solo_result = upload_batch(page, [solo_item], log, should_continue=should_continue)
                                healthy_results.extend(solo_result)
                                log(
                                    "info",
                                    f"Arquivo revalidado individualmente com sucesso: {solo_item.get('file_name')}",
                                )
                            except UploadFailed as solo_exc:
                                if "uploading error" in str(solo_exc).lower():
                                    corrupted_items.append(solo_item)
                                    log(
                                        "warning",
                                        f"Arquivo confirmado como corrompido: {solo_item.get('file_name')}",
                                        metadata={"file_name": solo_item.get("file_name"), "original_path": solo_item.get("original_path")},
                                    )
                                else:
                                    raise
                            # Recupera a area entre cada envio individual
                            try:
                                recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
                            except Exception:
                                pass

                        # Agora que a sessao foi recuperada (locks liberados), move os arquivos corrompidos
                        for corrupted_item in corrupted_items:
                            corrupted_name = corrupted_item.get("file_name")
                            corrupted_original_path = corrupted_item.get("original_path")
                            corrupted_file_id = corrupted_item.get("file_id")

                            if corrupted_original_path:
                                try:
                                    orig_path = Path(corrupted_original_path)
                                    if orig_path.exists():
                                        error_dir = orig_path.parent / "Error"
                                        error_dir.mkdir(parents=True, exist_ok=True)
                                        target_path = error_dir / orig_path.name
                                        # FIX #5 (MEDIUM): Evita colisao de nomes na pasta Error
                                        if target_path.exists():
                                            ts = int(time.time())
                                            target_path = error_dir / f"{orig_path.stem}_{ts}{orig_path.suffix}"
                                        shutil.move(str(orig_path), str(target_path))
                                        log(
                                            "info",
                                            f"Arquivo corrompido movido para pasta Error: {corrupted_name}",
                                            metadata={"target_path": str(target_path)},
                                        )
                                except Exception as move_exc:
                                    log("warning", f"Falha ao mover arquivo corrompido para Error: {move_exc}")

                            # A automacao NAO deve deletar arquivos da pasta temp.
                            # A copia temporaria do arquivo corrompido e preservada de proposito
                            # (o original ja foi movido para a pasta Error acima). A limpeza,
                            # quando necessaria, deve ser feita manualmente.

                            if on_file_error:
                                try:
                                    on_file_error(
                                        corrupted_file_id,
                                        f"Uploading error: Arquivo '{corrupted_name}' confirmado como corrompido e movido para a pasta Error.",
                                    )
                                except Exception as cb_exc:
                                    log("warning", f"Falha ao executar callback on_file_error: {cb_exc}")

                        # Propaga os resultados dos arquivos saudaveis
                        if healthy_results:
                            batch_result = healthy_results
                        else:
                            log("info", f"Todos os arquivos do lote {batch_number} foram confirmados como corrompidos.")
                            batch_result = []
                        break
                    else:
                        raise

                error_screenshot_saved = False
                if batch_result:
                    if on_batch_uploaded:
                        on_batch_uploaded(batch_number, batch_folder_path, batch_result)
                    uploaded.extend(batch_result)
                    for item in batch_result:
                        log(
                            "info",
                            f"Arquivo enviado: {item['file_name']}",
                            automation_id=payload.get("automation_id"),
                            file_id=item.get("file_id"),
                            metadata={"path": item.get("uploaded_path")},
                        )
                    log("info", f"Lote concluido: {batch_number}", metadata={"batch_folder_path": batch_folder_path, "count": len(batch)})
                break
            if index < len(batches):
                log(
                    "info",
                    "Continuando com proximo lote na mesma sessao do Chromium apos espera de 5 segundos.",
                    metadata={"next_batch": int(batches[index][0].get("batch_number") or (index + 1))},
                )
        return {
            "automation_id": payload.get("automation_id"),
            "workspace_id": payload.get("workspace_id"),
            "workspace_name": workspace_name,
            "uploaded_files": uploaded,
            "batch_size": batch_size,
        }
    except Exception:
        if browser and browser.page and not error_screenshot_saved:
            safe_error_screenshot(browser.page, task_id, log)
        raise
    finally:
        if browser:
            close_browser(browser, log, "Navegador fechado.")


def find_soffice() -> str | None:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable:
        return executable
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def convert_file_to_pdf(original_path: str, output_dir: str | None, log: Callable) -> str:
    source = Path(original_path)
    if not source.exists():
        raise UnsupportedFormat(f"Arquivo nao encontrado para conversao: {original_path}")
    if source.suffix.lower() == ".pdf":
        return str(source)
    if source.suffix.lower() not in SUPPORTED_OFFICE_EXTENSIONS:
        raise UnsupportedFormat(f"Formato sem conversor configurado: {source.suffix}")
    soffice = find_soffice()
    if not soffice:
        raise ManualReviewRequired("LibreOffice/soffice nao encontrado para conversao PDF.")
    target_dir = Path(output_dir) if output_dir else runtime_path("TEMP_PATH")
    target_dir.mkdir(parents=True, exist_ok=True)
    log("info", "Conversao PDF iniciada.")
    result = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(target_dir),
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise ManualReviewRequired(f"Falha na conversao PDF: {result.stderr or result.stdout}")
    pdf_path = target_dir / f"{source.stem}.pdf"
    if not pdf_path.exists():
        raise ManualReviewRequired("Conversao executada, mas PDF nao foi encontrado.")
    log("info", f"PDF criado: {pdf_path}")
    return str(pdf_path)
