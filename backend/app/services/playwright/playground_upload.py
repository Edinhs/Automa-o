from __future__ import annotations

import base64
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from app.core.config import runtime_path, settings
from app.services.playwright.browser import click_first, open_persistent_chromium, page_text, safe_error_screenshot
from app.services.playwright.errors import (
    ManualReviewRequired,
    PlaywrightAutomationError,
    RecoverableUploadUiError,
    UnsupportedFormat,
    UploadFailed,
)
from app.services.playwright.playground_login import configured_playground_url, ensure_logged_in
from app.services.playwright.playground_workspace import open_workspace, wait_for_workspace_area
from app.services.playwright.selectors import (
    CHOOSE_FILES_TEXTS,
    UPLOAD_ACTIVE_TEXTS,
    UPLOAD_COMPLETE_TEXTS,
    UPLOAD_ERROR_TEXTS,
    UPLOAD_FILES_TEXTS,
)


SUPPORTED_OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".csv"}
DEFAULT_BROWSER_RESTART_ATTEMPTS = 2
SAME_SESSION_RECOVERY_ATTEMPTS = 2
# Segundos sem o indicador "Uploading Files" necessarios para confirmar a conclusao do
# lote quando o Playground nao exibe um texto explicito de "Upload complete".
UPLOAD_COMPLETE_STABLE_SECONDS = 3
# Tempo maximo aguardando o lote iniciar o envio (verde "Uploading Files") ou dar erro
# (vermelho "Upload Error") apos clicar no Upload Files final.
BATCH_SENT_TIMEOUT_SECONDS = 30
# Janela curta apos o verde "Uploading Files" durante a qual ainda vigiamos o aparecimento
# de "Upload Error" (o erro costuma surgir no ultimo arquivo) antes de seguir ao proximo lote.
POST_SENT_ERROR_WATCH_SECONDS = 5
# Tempo maximo aguardando a conclusao total do ultimo lote antes de fechar o navegador,
# para nao truncar o envio do ultimo conjunto de arquivos.
FINAL_BATCH_COMPLETE_TIMEOUT_SECONDS = 180


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
        lookups = [
            lambda text=text: page.get_by_role("button", name=text),
            lambda text=text: page.locator(f"button:has-text('{text}')"),
            lambda text=text: page.locator(f"[role='button']:has-text('{text}')"),
            lambda text=text: page.get_by_text(text, exact=False),
        ]
        for lookup in lookups:
            try:
                locator = lookup(text)
                count = locator.count()
            except Exception:
                continue
            for index in range(count):
                candidate = locator.nth(index)
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
    """Aguarda confirmacao de que os arquivos foram realmente anexados antes do clique final.

    Hierarquia de evidencias (da mais forte para a mais fraca):
      1. Todos os nomes aparecem no body -> retorna imediatamente.
      2. Pelo menos UM nome aparece E o botao Upload Files esta habilitado (apos 5 s) ->
         evidencia parcial aceita, com aviso.
      3. Nenhum nome visivel mas botao habilitado por 5 s consecutivos -> aceita com aviso
         explicito (Playground pode exibir nomes de forma truncada/inacessivel via inner_text).
      4. Timeout de 60 s sem nenhuma evidencia -> levanta UploadFailed para nao clicar
         Upload "no escuro" (antigo comportamento: apenas logava warning e continuava).
    """
    expected_names = [str(item.get("file_name") or Path(item["path"]).name) for item in batch]
    started_at = time.monotonic()
    deadline = time.monotonic() + 60
    log("info", "Aguardando arquivos carregarem antes do Upload Files final.", metadata={"files": expected_names})
    button_enabled_since: float | None = None
    while time.monotonic() < deadline:
        check_continue(should_continue)
        body = page_text(page).lower()
        found = [name for name in expected_names if name.lower() in body]

        # Evidencia 1: todos os nomes confirmados na tela.
        if len(found) == len(expected_names):
            log("info", "Arquivos carregados na tela (todos os nomes confirmados).", metadata={"files": found})
            return

        elapsed = time.monotonic() - started_at
        button_on = final_upload_button_enabled(page)

        # Evidencia 2: pelo menos um nome visivel + botao habilitado (apos 5 s).
        if found and button_on and elapsed >= 5:
            log(
                "info",
                "Upload Files habilitado com parte dos arquivos visivel; prosseguindo.",
                metadata={"loaded": found, "missing": [n for n in expected_names if n not in found]},
            )
            return

        # Evidencia 3: botao habilitado por >= 5 s consecutivos mesmo sem nomes visiveis
        # (Playground pode truncar nomes na UI; botao habilitado e o sinal mais forte).
        if button_on:
            if button_enabled_since is None:
                button_enabled_since = time.monotonic()
            elif time.monotonic() - button_enabled_since >= 5:
                log(
                    "warning",
                    "Botao Upload Files habilitado por 5 s sem confirmar nomes na tela; prosseguindo com cautela.",
                    metadata={"expected": expected_names, "visible_body_sample": body[:300]},
                )
                return
        else:
            button_enabled_since = None

        if found:
            log("info", "Parte dos arquivos ja aparece na tela.", metadata={"loaded": found, "expected": expected_names})
        time.sleep(1)

    # Nenhuma evidencia de que os arquivos foram anexados: nao clicar Upload no escuro.
    raise UploadFailed(
        f"Arquivos nao confirmados como anexados apos 60 s: {expected_names}. "
        "Abortando para evitar clique de Upload sem arquivos reais."
    )


def final_upload_button_enabled(page) -> bool:
    for text in UPLOAD_FILES_TEXTS:
        lookups = [
            lambda text=text: page.get_by_role("button", name=text),
            lambda text=text: page.locator(f"button:has-text('{text}')"),
            lambda text=text: page.locator(f"[role='button']:has-text('{text}')"),
            lambda text=text: page.get_by_text(text, exact=False),
        ]
        for lookup in lookups:
            try:
                locator = lookup(text)
                count = locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    if candidate.is_visible(timeout=500) and candidate.is_enabled(timeout=500):
                        return True
            except Exception:
                continue
    return False


def body_has_upload_error(page) -> bool:
    """True quando o Playground exibe a mensagem de erro (vermelho) de upload."""
    body = page_text(page).lower()
    return any(text.lower() in body for text in UPLOAD_ERROR_TEXTS)


def upload_area_choose_present(page) -> bool:
    """A area de selecao (Choose Files / input de arquivo) ja esta disponivel na tela."""
    for text in CHOOSE_FILES_TEXTS:
        for lookup in (
            lambda text=text: page.get_by_role("button", name=text),
            lambda text=text: page.get_by_text(text, exact=False),
        ):
            try:
                locator = lookup()
                if locator.count() and locator.first.is_visible(timeout=500):
                    return True
            except Exception:
                continue
    try:
        if page.locator('input[type="file"]').count():
            return True
    except Exception:
        pass
    return False


def ensure_upload_area_open(page, log: Callable) -> None:
    """Abre a area de upload apenas se o Choose Files ainda nao estiver visivel.

    No novo fluxo, lotes subsequentes reaproveitam a mesma tela sem recarregar; o
    Choose Files costuma continuar disponivel, entao nao reabrimos a area a cada lote.
    """
    if upload_area_choose_present(page):
        return
    click_upload_files(page, log)


def _body_has_active(body_lower: str) -> bool:
    return any(text.lower() in body_lower for text in UPLOAD_ACTIVE_TEXTS)


def _body_has_complete(body_lower: str) -> bool:
    return any(text.lower() in body_lower for text in UPLOAD_COMPLETE_TEXTS)


def wait_for_batch_sent(
    page,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    *,
    pre_click_body: str = "",
) -> None:
    """Aguarda o lote iniciar o envio (verde "Uploading Files") ou dar erro (vermelho).

    Levanta UploadFailed("uploading error") ao ver o vermelho; levanta UploadFailed
    generico se nada acontecer dentro de BATCH_SENT_TIMEOUT_SECONDS.

    pre_click_body (opcional): snapshot do body ANTES do clique de upload, em lower-case.
    Usado para eliminar o falso positivo em que UPLOAD_COMPLETE_TEXTS ja estava presente
    na tela de sessoes anteriores antes de este lote comecar a subir.

    Regra de conclusao:
      - Prioridade 1: verde UPLOAD_ACTIVE_TEXTS aparece  -> confirmado, retorna.
      - Prioridade 2: UPLOAD_COMPLETE_TEXTS aparece SOMENTE se o texto NAO estava no
        snapshot pre-clique (i.e. surgiu DEPOIS do clique desta sessao).  Isso evita que
        labels de arquivos ja enviados ("Uploaded", "Upload date", "Concluido") disparem
        o retorno precoce.
      - Nunca retorna por UPLOAD_COMPLETE_TEXTS isolado sem transicao observada.
    """
    deadline = time.monotonic() + BATCH_SENT_TIMEOUT_SECONDS
    # Textos de "complete" pre-existentes no snapshot (antes do clique).
    pre_complete_tokens = {text.lower() for text in UPLOAD_COMPLETE_TEXTS if text.lower() in pre_click_body}
    if pre_complete_tokens:
        log(
            "info",
            "Snapshot pre-clique contem textos de conclusao; ignorando-os como indicador de envio deste lote.",
            metadata={"pre_complete_tokens": sorted(pre_complete_tokens)},
        )

    while time.monotonic() < deadline:
        check_continue(should_continue)
        body = page_text(page).lower()

        # Erro vermelho tem prioridade maxima.
        if any(text.lower() in body for text in UPLOAD_ERROR_TEXTS):
            raise UploadFailed("uploading error")

        # Verde "Uploading Files": evidencia positiva de que este lote iniciou o envio.
        if _body_has_active(body):
            log("info", "Uploading Files (verde) detectado; lote enviado.")
            return

        # "Upload complete" / "Uploaded" etc. so vale como sinal de conclusao se surgiu
        # APOS o clique, ou seja, se NAO estava no snapshot pre-clique.
        # Avaliamos token a token: um novo token de conclusao que nao estava antes indica
        # que o Playground processou o lote e exibiu o resultado.
        new_complete_tokens = {
            text.lower()
            for text in UPLOAD_COMPLETE_TEXTS
            if text.lower() in body and text.lower() not in pre_complete_tokens
        }
        if new_complete_tokens:
            log(
                "info",
                "Upload concluido diretamente (novo texto de conclusao detectado apos o clique).",
                metadata={"new_complete_tokens": sorted(new_complete_tokens)},
            )
            return

        time.sleep(0.4)

    if body_has_upload_error(page):
        raise UploadFailed("uploading error")
    raise UploadFailed("Lote nao iniciou o envio no tempo esperado (30s).")


def watch_for_error_window(page, seconds: int, should_continue: Callable[[], bool] | None = None) -> bool:
    """Vigia por 'Upload Error' por uma janela curta. Retorna True se o erro aparecer."""
    deadline = time.monotonic() + max(0, seconds)
    while time.monotonic() < deadline:
        check_continue(should_continue)
        if body_has_upload_error(page):
            return True
        time.sleep(0.4)
    return False


def wait_for_batch_complete(page, log: Callable, should_continue: Callable[[], bool] | None = None) -> None:
    """Aguarda a conclusao total do lote (usado no ultimo lote, antes de fechar o navegador).

    Conclusao reconhecida por (1) texto de conclusao presente sem indicador ativo, ou
    (2) o indicador "Uploading Files" sumiu de forma estavel por UPLOAD_COMPLETE_STABLE_SECONDS.
    """
    deadline = time.monotonic() + FINAL_BATCH_COMPLETE_TIMEOUT_SECONDS
    saw_active = True
    absent_since: float | None = None
    while time.monotonic() < deadline:
        check_continue(should_continue)
        body = page_text(page).lower()
        if any(text.lower() in body for text in UPLOAD_ERROR_TEXTS):
            raise UploadFailed("uploading error")
        has_active = any(text.lower() in body for text in UPLOAD_ACTIVE_TEXTS)
        has_complete = any(text.lower() in body for text in UPLOAD_COMPLETE_TEXTS)
        if has_active:
            saw_active = True
            absent_since = None
        elif has_complete:
            log("info", "Ultimo lote concluido (texto de conclusao detectado).")
            return
        elif saw_active:
            if absent_since is None:
                absent_since = time.monotonic()
            elif time.monotonic() - absent_since >= UPLOAD_COMPLETE_STABLE_SECONDS:
                log("info", "Ultimo lote concluido (indicador de envio desapareceu).")
                return
        time.sleep(1.0)
    log("warning", "Nao foi possivel confirmar a conclusao do ultimo lote no tempo limite; seguindo para fechar o navegador.")


def detect_errored_file_name(page, batch: list[dict[str, Any]]):
    """Tenta identificar, de forma rapida, qual arquivo do lote disparou o 'Upload Error'.

    Estrategia (fast-path do modo hibrido):
      1. Procura a linha/elemento marcado com a mensagem de erro e casa o nome de arquivo
         do lote contido no container dessa linha.
      2. Se nao houver marcacao casavel, e apenas UM nome do lote estiver visivel na tela,
         assume ser ele (o erro costuma aparecer no ultimo arquivo tentado).
    Retorna o item do lote ou None quando ambiguo (o chamador cai para o isolamento 1 a 1).
    """
    expected = {str(item.get("file_name") or Path(item["path"]).name): item for item in batch}
    for err in UPLOAD_ERROR_TEXTS:
        try:
            markers = page.get_by_text(err, exact=False)
            count = min(markers.count(), 5)
        except Exception:
            continue
        for index in range(count):
            try:
                container = markers.nth(index).locator(
                    "xpath=ancestor-or-self::*[self::li or self::tr or self::div][1]"
                )
                text = container.first.inner_text(timeout=500)
            except Exception:
                continue
            for name, item in expected.items():
                if name.lower() in (text or "").lower():
                    return item
    body = page_text(page).lower()
    present = [item for name, item in expected.items() if name.lower() in body]
    if len(present) == 1:
        return present[0]
    return None


def move_corrupted_temp_to_error(item: dict[str, Any], log: Callable) -> str | None:
    """Recorta a copia em TEMP do arquivo corrompido para uma pasta 'ERROR' no proprio temp.

    Mantem o original na pasta monitorada intacto; a pasta ERROR sinaliza para o usuario
    fazer a acao manual. Retorna o caminho de destino quando o arquivo e movido.
    """
    temp_path = item.get("temp_path") or item.get("path")
    if not temp_path:
        return None
    source = Path(temp_path)
    if not source.exists():
        log("warning", f"Arquivo corrompido nao encontrado no temp para mover: {item.get('file_name')}", metadata={"temp_path": str(temp_path)})
        return None
    error_dir = source.parent / "ERROR"
    error_dir.mkdir(parents=True, exist_ok=True)
    target = error_dir / source.name
    if target.exists():
        target = error_dir / f"{source.stem}_{int(time.time())}{source.suffix}"
    try:
        shutil.move(str(source), str(target))
    except Exception as exc:
        log("warning", f"Falha ao recortar arquivo corrompido para a pasta ERROR: {exc}", metadata={"temp_path": str(temp_path)})
        return None
    log("info", f"Arquivo corrompido recortado para a pasta ERROR (temp): {item.get('file_name')}", metadata={"target_path": str(target)})
    return str(target)


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

    # Tenta do último para o primeiro (varredura reversa), pois botões reais costumam vir depois
    for index in reversed(range(count)):
        button = locator.nth(index)
        try:
            if not button.is_visible(timeout=500):
                continue
            
            # Se encontrar o botão mas ele estiver desabilitado, avisa mas continua procurando
            if not button.is_enabled(timeout=500):
                log("warning", f"Candidato final Upload Files na posicao {index} encontrado, mas desabilitado.")
                continue

            button.click(timeout=5000)
            log("info", f"Upload Files final clicado com sucesso na posicao {index}.")
            return True
        except Exception as exc:
            if final_upload_click_error_is_recoverable(exc):
                continue
            raise
    return False


def click_final_upload_with_recovery(page, log: Callable, should_continue: Callable[[], bool] | None = None) -> None:
    last_error = None
    for attempt in range(1, 6):
        check_continue(should_continue)
        try:
            for text in UPLOAD_FILES_TEXTS:
                lookups = [
                    lambda text=text: page.get_by_role("button", name=text),
                    lambda text=text: page.locator(f"button:has-text('{text}')"),
                    lambda text=text: page.locator(f"[role='button']:has-text('{text}')"),
                    lambda text=text: page.get_by_text(text, exact=False),
                ]
                for lookup in lookups:
                    locator = lookup(text)
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
        direct_url = str(payload.get("workspace_playground_url") or "").strip()
        if direct_url:
            # Novo fluxo: abre o workspace direto pela URL salva, sem pesquisar pelo nome.
            page.goto(direct_url, wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
            ensure_logged_in(page, payload, log)
            check_continue(should_continue)
            if recovery:
                log("info", "Reabrindo workspace pela URL direta apos reinicio do Chromium.")
            if wait_for_workspace_area(page, "upload", timeout_ms=settings.WORKSPACE_AREA_TIMEOUT_MS):
                log("info", "Workspace aberto direto pela Playground URL.", metadata={"workspace_playground_url": direct_url})
            else:
                log("warning", "Playground URL direta nao carregou a area de upload; caindo para a busca por nome.")
                open_workspace(page, workspace_name, log)
        else:
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


def uploaded_results(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "file_name": item.get("file_name") or Path(item["path"]).name,
            "uploaded_path": item["path"],
            "status": "uploaded",
        }
        for item in batch
    ]


def upload_batch(
    page,
    batch: list[dict[str, Any]],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    *,
    is_last_batch: bool = False,
) -> list[dict[str, Any]]:
    """Envia um lote (pasta) na tela de upload ja aberta.

    Fluxo: garante a area de Choose Files aberta (sem recarregar), seleciona todos os
    arquivos do lote, aguarda carregarem e clica no Upload Files final (azul). Considera o
    lote ENVIADO ao surgir o verde "Uploading Files" e, a partir dai, segue direto para o
    proximo lote. Se surgir o vermelho "Upload Error", levanta UploadFailed("uploading error")
    para o chamador isolar o arquivo corrompido.

    No ultimo lote (is_last_batch=True), NAO espera conclusao: assim que o verde "Uploading
    Files" aparece, retorna e o navegador fecha (decisao do usuario). O monitoramento unico
    posterior detecta e trata os arquivos nao-Ready (deletar + PDF + reenviar).
    """
    paths = [str(Path(item["path"]).resolve()) for item in batch]
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        raise UploadFailed(f"Arquivo(s) nao encontrado(s): {missing}")
    check_continue(should_continue)
    ensure_upload_area_open(page, log)
    check_continue(should_continue)
    choose_files(page, paths, log)
    check_continue(should_continue)
    wait_for_selected_files(page, batch, log, should_continue=should_continue)

    # Captura o estado do body ANTES do clique de upload para eliminar falsos positivos:
    # textos de "Upload complete"/"Uploaded" ja presentes na tela (arquivos de sessoes
    # anteriores, coluna "Upload date", etc.) nao devem ser contados como evidencia de
    # que ESTE lote iniciou o envio.
    pre_click_body = page_text(page).lower()

    click_final_upload_with_recovery(page, log, should_continue=should_continue)

    # Aguarda o lote iniciar o envio (verde "Uploading Files") ou dar erro (vermelho).
    # O snapshot pre-clique e passado para que o falso positivo de UPLOAD_COMPLETE_TEXTS
    # pre-existente seja ignorado.
    wait_for_batch_sent(page, log, should_continue=should_continue, pre_click_body=pre_click_body)

    if is_last_batch:
        # Decisao do usuario: assim que o verde "Uploading Files" aparece, FECHA o Chromium sem
        # esperar a conclusao nem janela de erro. O monitoramento unico (que roda depois desta
        # task de upload) detecta qualquer arquivo nao-Ready (error/processing) e trata:
        # deletar na web + converter para PDF + reenviar.
        log("info", "Ultimo lote enviado (Uploading Files); fechando o Chromium sem esperar.")
    else:
        # Entre lotes: janela curta vigiando o vermelho (o erro costuma surgir no ultimo arquivo
        # do lote) antes de seguir direto ao Choose Files do proximo lote, sem recarregar a tela.
        if watch_for_error_window(page, POST_SENT_ERROR_WATCH_SECONDS, should_continue=should_continue):
            raise UploadFailed("uploading error")
        log("info", "Lote enviado; seguindo ao proximo lote na mesma tela.")
    return uploaded_results(batch)


def finalize_corrupted(corrupted_items: list[dict[str, Any]], log: Callable, on_file_error: Callable | None) -> None:
    """Recorta cada corrompido para a pasta ERROR (temp) e notifica via on_file_error."""
    for corrupted_item in corrupted_items:
        corrupted_name = corrupted_item.get("file_name")
        moved = move_corrupted_temp_to_error(corrupted_item, log)
        if on_file_error:
            try:
                suffix = " e recortado para a pasta ERROR" if moved else ""
                on_file_error(
                    corrupted_item.get("file_id"),
                    f"Uploading error: arquivo '{corrupted_name}' confirmado como corrompido{suffix}.",
                )
            except Exception as cb_exc:
                log("warning", f"Falha ao executar callback on_file_error: {cb_exc}")


def isolate_one_by_one(
    page,
    batch: list[dict[str, Any]],
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    on_file_error: Callable | None,
    should_continue: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Fallback robusto: reenvia cada arquivo do lote individualmente para isolar os corrompidos.

    Nunca move um arquivo saudavel: so confirma corrompido o arquivo que falha sozinho.
    """
    corrupted_items: list[dict[str, Any]] = []
    healthy_results: list[dict[str, Any]] = []
    try:
        recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
    except Exception as recovery_exc:
        log("warning", "Recuperacao da area de upload falhou antes do isolamento individual.", metadata={"error": str(recovery_exc)})
    for solo_item in list(batch):
        check_continue(should_continue)
        try:
            healthy_results.extend(upload_batch(page, [solo_item], log, should_continue=should_continue))
            log("info", f"Arquivo revalidado individualmente com sucesso: {solo_item.get('file_name')}")
        except UploadFailed as solo_exc:
            if "uploading error" not in str(solo_exc).lower():
                raise
            corrupted_items.append(solo_item)
            log("warning", f"Arquivo confirmado como corrompido: {solo_item.get('file_name')}", metadata={"file_name": solo_item.get("file_name")})
        try:
            recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
        except Exception:
            pass
    finalize_corrupted(corrupted_items, log, on_file_error)
    return healthy_results


def handle_uploading_error(
    page,
    batch: list[dict[str, Any]],
    batch_number: int,
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    on_file_error: Callable | None,
    should_continue: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Modo hibrido de tratamento do 'Upload Error'.

    Fast-path: identifica o provavel corrompido (ultimo/destacado) e valida reenviando o
    RESTANTE do lote; se o restante sobe sem erro, o candidato esta confirmado (e movido para
    ERROR). Se a identificacao for ambigua ou o restante ainda falhar, cai para o isolamento
    1 a 1. Retorna os resultados dos arquivos saudaveis (pode ser lista vazia).
    """
    # Identifica o candidato ANTES de recuperar a area (a marca de erro some apos o reload).
    candidate = detect_errored_file_name(page, batch)
    # Libera os locks de arquivo do Windows que o Chromium mantem durante o upload.
    try:
        recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
    except Exception as recovery_exc:
        log("warning", "Recuperacao da area de upload falhou antes de tratar o corrompido.", metadata={"error": str(recovery_exc)})

    if candidate is not None:
        candidate_name = candidate.get("file_name")
        remainder = [item for item in batch if item is not candidate]
        if not remainder:
            log("info", f"Lote {batch_number} continha apenas o arquivo corrompido: {candidate_name}.")
            finalize_corrupted([candidate], log, on_file_error)
            return []
        log(
            "info",
            f"Provavel corrompido (fast-path): {candidate_name}. Reenviando os {len(remainder)} demais do lote {batch_number}.",
            metadata={"candidate": candidate_name},
        )
        try:
            result = upload_batch(page, remainder, log, should_continue=should_continue)
            finalize_corrupted([candidate], log, on_file_error)
            return result
        except UploadFailed as exc:
            if "uploading error" not in str(exc).lower():
                raise
            log("warning", f"Reenvio do restante do lote {batch_number} ainda deu erro; caindo para o isolamento 1 a 1.", metadata={"candidate": candidate_name})
            try:
                recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
            except Exception:
                pass

    return isolate_one_by_one(page, batch, payload, workspace_name, log, on_file_error, should_continue)


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
                    # Sem recarregar entre lotes: apos o lote anterior iniciar o envio
                    # (verde "Uploading Files"), seguimos direto ao Choose Files do proximo
                    # lote na mesma tela. O ultimo lote aguarda a conclusao total.
                    batch_result = upload_batch(
                        page,
                        batch,
                        log,
                        should_continue=should_continue,
                        is_last_batch=(index == len(batches)),
                    )
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
                    if "uploading error" not in str(exc).lower():
                        raise
                    if not batch:
                        raise
                    # Screenshot de diagnostico antes de qualquer operacao de recuperacao/IO.
                    error_screenshot_saved = save_recovery_screenshot(browser, task_id, log)
                    log(
                        "warning",
                        f"Upload Error detectado no Playground no lote {batch_number}; identificando o arquivo corrompido (modo hibrido).",
                        metadata={"batch": batch_number, "files": [i.get("file_name") for i in batch]},
                    )
                    # Modo hibrido: tenta pelo ultimo/destacado e cai para 1-a-1 se ambiguo.
                    # Nao usa 'break': cai no checkpoint abaixo para registrar os saudaveis.
                    batch_result = handle_uploading_error(
                        page,
                        batch,
                        batch_number,
                        payload,
                        workspace_name,
                        log,
                        on_file_error,
                        should_continue=should_continue,
                    )
                    if not batch_result:
                        log("info", f"Todos os arquivos do lote {batch_number} foram confirmados como corrompidos.")

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


def libreoffice_profile_uri(target_dir: Path) -> str:
    """URI de um perfil de usuario dedicado e limpo para o LibreOffice headless.

    Um perfil proprio evita prompts de "outra instancia aberta"/restauracao e permite a
    conversao de arquivos confidenciais sem travar em dialogos de permissao do Office:
    em modo headless o LibreOffice prossegue sem habilitar macros nem aguardar interacao.
    """
    profile_dir = target_dir / ".lo_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return profile_dir.resolve().as_uri()


# Extensoes por aplicativo do Office que sabemos converter para PDF via COM.
WORD_COM_EXTENSIONS = {".doc", ".docx", ".docm", ".dot", ".dotx", ".rtf", ".odt", ".txt"}
EXCEL_COM_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".xlsb", ".csv", ".ods"}
POWERPOINT_COM_EXTENSIONS = {".ppt", ".pptx", ".pptm", ".odp"}

# Script PowerShell que dirige o Office (Word/Excel/PowerPoint) por COM e exporta para PDF.
# Os caminhos chegam por variaveis de ambiente (HUB_SRC/HUB_DST/HUB_KIND) para evitar
# problemas de aspas/escape e injecao. Roda via -EncodedCommand, que NAO esbarra na
# ExecutionPolicy de arquivos .ps1 (comum em notebooks corporativos travados).
_OFFICE_COM_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$src = $env:HUB_SRC
$dst = $env:HUB_DST
$kind = $env:HUB_KIND
$app = $null
try {
    if ($kind -eq 'word') {
        $app = New-Object -ComObject Word.Application
        $app.Visible = $false
        $app.DisplayAlerts = 0
        $doc = $app.Documents.Open($src, $false, $true, $false)
        $doc.ExportAsFixedFormat($dst, 17)   # wdExportFormatPDF = 17
        $doc.Close()
    } elseif ($kind -eq 'excel') {
        $app = New-Object -ComObject Excel.Application
        $app.Visible = $false
        $app.DisplayAlerts = $false
        $wb = $app.Workbooks.Open($src, 0, $true)
        $wb.ExportAsFixedFormat(0, $dst)     # xlTypePDF = 0
        $wb.Close($false)
    } elseif ($kind -eq 'powerpoint') {
        $app = New-Object -ComObject PowerPoint.Application
        $pres = $app.Presentations.Open($src, $true, $false, $false)  # ReadOnly, Untitled, sem janela
        $pres.SaveAs($dst, 32)               # ppSaveAsPDF = 32
        $pres.Close()
    } else {
        throw "kind invalido: $kind"
    }
} finally {
    if ($app -ne $null) { try { $app.Quit() } catch {} }
}
"""


def office_com_kind(suffix: str) -> str | None:
    lower = (suffix or "").lower()
    if lower in WORD_COM_EXTENSIONS:
        return "word"
    if lower in EXCEL_COM_EXTENSIONS:
        return "excel"
    if lower in POWERPOINT_COM_EXTENSIONS:
        return "powerpoint"
    return None


def convert_office_via_com(source: Path, target_pdf: Path, log: Callable) -> bool:
    """Converte para PDF via Microsoft Office (COM) usando PowerShell. True se gerou o PDF.

    Usa o Office ja instalado na maquina (Word/Excel/PowerPoint): funciona offline, nao exige
    LibreOffice e nao adiciona dependencia Python. Em maquina sem Windows ou com formato fora
    do Office, retorna False para o chamador cair no LibreOffice.
    """
    if os.name != "nt":
        return False
    kind = office_com_kind(source.suffix)
    if not kind:
        return False
    encoded = base64.b64encode(_OFFICE_COM_PS_SCRIPT.encode("utf-16-le")).decode("ascii")
    env = {**os.environ, "HUB_SRC": str(source), "HUB_DST": str(target_pdf), "HUB_KIND": kind}
    log("info", f"Conversao PDF via Microsoft Office ({kind}) iniciada.")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
    except Exception as exc:
        log("warning", f"Conversao via Office (COM) nao executou: {exc}")
        return False
    if result.returncode == 0 and target_pdf.exists():
        return True
    detail = (result.stderr or result.stdout or "").strip()
    log("warning", f"Conversao via Office (COM) nao concluiu ({kind}): {detail[:500] or 'sem detalhe'}")
    return False


def convert_file_to_pdf(original_path: str, output_dir: str | None, log: Callable) -> str:
    source = Path(original_path)
    if not source.exists():
        raise UnsupportedFormat(f"Arquivo nao encontrado para conversao: {original_path}")
    if source.suffix.lower() == ".pdf":
        return str(source)
    if source.suffix.lower() not in SUPPORTED_OFFICE_EXTENSIONS:
        raise UnsupportedFormat(f"Formato sem conversor configurado: {source.suffix}")
    target_dir = Path(output_dir) if output_dir else runtime_path("TEMP_PATH")
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / f"{source.stem}.pdf"
    log("info", "Conversao PDF iniciada.")

    # 1) Microsoft Office (COM): usa o Office ja instalado, offline e sem LibreOffice.
    if convert_office_via_com(source, pdf_path, log):
        log("info", f"PDF criado via Microsoft Office: {pdf_path}")
        return str(pdf_path)

    # 2) Fallback: LibreOffice/soffice, se estiver instalado.
    soffice = find_soffice()
    if not soffice:
        raise ManualReviewRequired(
            "Conversao PDF indisponivel: Microsoft Office (COM) nao converteu e LibreOffice/soffice nao foi encontrado."
        )
    # Remove um PDF parcial que uma tentativa COM falha possa ter deixado, para que o
    # 'pdf_path.exists()' apos o LibreOffice signifique mesmo que ELE gerou o arquivo.
    try:
        pdf_path.unlink(missing_ok=True)
    except OSError:
        pass
    result = subprocess.run(
        [
            soffice,
            "--headless",
            # Flags que evitam dialogos de permissao/seguranca/restauracao em arquivos
            # confidenciais (a conversao prossegue sem interacao do usuario).
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            "--nologo",
            "--nofirststartwizard",
            f"-env:UserInstallation={libreoffice_profile_uri(target_dir)}",
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
    if not pdf_path.exists():
        raise ManualReviewRequired("Conversao executada, mas PDF nao foi encontrado.")
    log("info", f"PDF criado via LibreOffice: {pdf_path}")
    return str(pdf_path)


def convert_to_pdf_in_folder(source_path: str, pdf_dir: str, log: Callable) -> str:
    """Recorta o arquivo de origem para a pasta 'PDF' (no temp) e o converte para PDF ali.

    Usado no retry pos-monitoramento: o arquivo nao-Ready e movido para uma pasta PDF dentro
    do staging e convertido no mesmo lugar antes do reenvio.
    """
    destination = Path(pdf_dir)
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(source_path)
    if not source.exists():
        raise UnsupportedFormat(f"Arquivo nao encontrado para mover/converter: {source_path}")
    moved = destination / source.name
    try:
        if source.resolve() != moved.resolve():
            if moved.exists():
                moved = destination / f"{source.stem}_{int(time.time())}{source.suffix}"
            shutil.move(str(source), str(moved))
            log("info", f"Arquivo recortado para a pasta PDF: {moved.name}", metadata={"pdf_dir": str(destination)})
    except Exception as exc:
        log("warning", f"Falha ao recortar para a pasta PDF; convertendo do local original: {exc}")
        moved = source
    return convert_file_to_pdf(str(moved), str(destination), log)
