from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
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
    DISMISS_BANNER_TEXTS,
    UPLOAD_ACTIVE_TEXTS,
    UPLOAD_COMPLETE_TEXTS,
    UPLOAD_ERROR_TEXTS,
    UPLOAD_FILES_TEXTS,
)

# Padrao para reconhecer URLs de upload real nas requisicoes de rede capturadas.
# Cobre: /upload, /file(s), /document(s), /ingest, /s3, /blob, /object, /chunk, /import, /attach.
_UPLOAD_URL_PATTERN = re.compile(
    r"/(upload|file|files|document|documents|ingest|s3|blob|object|chunk|import|attach)",
    re.IGNORECASE,
)


# Extensoes por aplicativo do Office que sabemos converter para PDF via COM.
WORD_COM_EXTENSIONS = {".doc", ".docx", ".docm", ".dot", ".dotx", ".rtf", ".odt", ".txt"}
EXCEL_COM_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".xlsb", ".csv", ".ods"}
POWERPOINT_COM_EXTENSIONS = {".ppt", ".pptx", ".pptm", ".odp"}
# Porteira de conversao: a UNIAO completa do que o COM (ou o fallback LibreOffice) converte.
# Tem de espelhar os conjuntos acima -- nao restringir, senao formatos validos como .docm/.rtf/
# .xlsm viram manual_review sem nem tentar converter.
SUPPORTED_OFFICE_EXTENSIONS = WORD_COM_EXTENSIONS | EXCEL_COM_EXTENSIONS | POWERPOINT_COM_EXTENSIONS
DEFAULT_BROWSER_RESTART_ATTEMPTS = 2
SAME_SESSION_RECOVERY_ATTEMPTS = 2
# SLAs de confirmacao de upload -- valores default em settings (config.py), ajustaveis via .env
# sem rebuild. Mantemos os nomes de modulo como alias para nao mexer nos usos existentes.
# - UPLOAD_COMPLETE_STABLE_SECONDS: segundos sem "Uploading Files" para confirmar a conclusao do
#   lote quando o Playground nao exibe um texto explicito de "Upload complete".
UPLOAD_COMPLETE_STABLE_SECONDS = settings.UPLOAD_COMPLETE_STABLE_SECONDS
# - BATCH_SENT_TIMEOUT_SECONDS: tempo maximo aguardando o lote iniciar o envio (verde "Uploading
#   Files") ou dar erro (vermelho "Upload Error") apos clicar no Upload Files final.
BATCH_SENT_TIMEOUT_SECONDS = settings.BATCH_SENT_TIMEOUT_SECONDS
# - POST_SENT_ERROR_WATCH_SECONDS: janela curta apos o verde durante a qual ainda vigiamos o
#   aparecimento de "Upload Error" (costuma surgir no ultimo arquivo) antes do proximo lote.
POST_SENT_ERROR_WATCH_SECONDS = settings.POST_SENT_ERROR_WATCH_SECONDS
# - FINAL_BATCH_COMPLETE_TIMEOUT_SECONDS: tempo maximo aguardando a conclusao total do ultimo lote
#   antes de fechar o navegador, para nao truncar o envio do ultimo conjunto de arquivos.
FINAL_BATCH_COMPLETE_TIMEOUT_SECONDS = settings.FINAL_BATCH_COMPLETE_TIMEOUT_SECONDS


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
    # Na pagina do Workspace o "Upload files" e um <a> (Cloudscape Button href -> link), nao um
    # <button>; por isso incluimos get_by_role("link") e a:has-text alem dos seletores de botao.
    # Assim a automacao acha o controle que abre o Add Data sem depender so do get_by_text.
    for text in UPLOAD_FILES_TEXTS:
        lookups = [
            lambda text=text: page.get_by_role("button", name=text),
            lambda text=text: page.get_by_role("link", name=text),
            lambda text=text: page.locator(f"button:has-text('{text}')"),
            lambda text=text: page.locator(f"a:has-text('{text}')"),
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


def _count_files_in_inputs(page) -> int:
    """Conta via JS quantos arquivos estao realmente presos aos inputs[type=file] da pagina."""
    try:
        return int(
            page.evaluate(
                "Array.from(document.querySelectorAll('input[type=file]'))"
                ".reduce((n, el) => n + (el.files ? el.files.length : 0), 0)"
            )
        )
    except Exception:
        return -1  # -1 indica que nao foi possivel avaliar (pagina em transicao)


def choose_files(page, paths: list[str], log: Callable) -> None:
    """Abre o file-chooser (ou usa o input direto) e registra, como DIAGNOSTICO, quantos
    arquivos ficaram presos aos inputs.

    A contagem 0 NAO e fatal: o Playground (React) costuma ler os arquivos do file chooser
    para o estado da app e limpar/descartar input.files, ou usar um input em shadow DOM que
    querySelectorAll(document) nao alcanca. A confirmacao REAL do envio fica por conta de
    wait_for_batch_sent (rede / verde "Uploading Files" pos-clique) + timeout.
    """
    expected_count = len(paths)
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
        log("info", "Arquivos selecionados via file chooser.")
    except Exception:
        file_input = page.locator('input[type="file"]').first
        if file_input.count():
            file_input.set_input_files(paths, timeout=5000)
            log("info", "Arquivos selecionados via input file direto.")
        else:
            raise

    # --- Verificacao real de anexo (sinal 1) ---
    # Aguarda ate 3 s para que o browser registre os arquivos no FileList do input.
    attached_count = -1
    for _attempt in range(6):
        attached_count = _count_files_in_inputs(page)
        if attached_count >= expected_count:
            break
        time.sleep(0.5)

    log(
        "info",
        "Verificacao de anexo: arquivos detectados nos inputs.",
        metadata={
            "expected": expected_count,
            "detected": attached_count,
            "paths": paths,
        },
    )

    if attached_count <= 0:
        # NAO fatal: em producao o file chooser entregou os arquivos, mas input.files ficou
        # 0 (React consome e limpa o input, ou input em shadow DOM fora do alcance do JS).
        # Bloquear aqui era falso negativo (fechava sem tentar enviar). Seguimos; quem decide
        # de verdade e wait_for_batch_sent (rede / verde pos-clique) + o timeout.
        log(
            "warning",
            "Nenhum arquivo visto em input[type=file] via JS (normal no Playground React: "
            "le os arquivos e limpa o input). Prosseguindo; envio sera confirmado por rede/verde.",
            metadata={"expected": expected_count, "detected": attached_count},
        )
    elif attached_count < expected_count:
        log(
            "warning",
            "Anexo parcial detectado; prosseguindo (Playground pode usar multiplos inputs).",
            metadata={"expected": expected_count, "detected": attached_count},
        )


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


def final_upload_submit_locators(page) -> list[Callable]:
    """Locators do botao 'Upload files' FINAL (submit) da tela Add Data, do mais preciso ao mais
    generico.

    O DOM real (AWS Cloudscape) tem 3 elementos com 'Upload': o link do Workspace (<a>), a ABA
    'Upload Files' (button type=button, SEMPRE habilitada) e o SUBMIT real (button type=submit,
    variant-primary, desabilitado ate anexar). 'type=submit' isola o SUBMIT da aba e do link —
    por isso vem primeiro; assim nunca confirmamos/clicamos a aba por engano.
    """
    return [
        lambda: page.locator('button[type="submit"][class*="awsui_variant-primary"]'),
        lambda: page.locator('button[type="submit"]').filter(has_text=re.compile(r"upload|enviar", re.I)),
    ]


def final_upload_button_enabled(page) -> bool:
    # So o SUBMIT real conta como "pronto": a ABA 'Upload Files' (type=button) fica sempre
    # habilitada e daria falso positivo (foi o que o DOM ao vivo mostrou).
    for factory in final_upload_submit_locators(page):
        try:
            locator = factory()
            for index in range(locator.count()):
                candidate = locator.nth(index)
                if candidate.is_visible(timeout=500) and candidate.is_enabled(timeout=500):
                    return True
        except Exception:
            continue
    # Fallback para UIs sem o submit Cloudscape: por texto, excluindo a aba de tabs.
    for text in UPLOAD_FILES_TEXTS:
        try:
            locator = page.locator(f"button:has-text('{text}'):not([class*='tabs-tab'])")
            for index in range(locator.count()):
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


def is_corruption_suspect(exc: Exception) -> bool:
    """True quando uma UploadFailed indica que o lote pode conter um arquivo corrompido.

    Dois sinais levam ao mesmo tratamento de isolamento (mover o culpado para ERROR e
    seguir com os saudaveis):
      - "uploading error": o vermelho explicito do Playground;
      - "lote nao confirmado": timeout de wait_for_batch_sent (verde sem 2xx, 0 arquivos
        no input) tipico do arquivo-lixo (ex.: lock do Office '~$...docx').

    Mantemos a confirmacao REAL de envio em wait_for_batch_sent intacta: este predicado
    apenas decide o ROTEAMENTO da excecao para o isolamento, sem afrouxar a confirmacao.
    """
    message = str(exc or "").lower()
    return "uploading error" in message or "lote nao confirmado" in message


def verify_batch_present_in_workspace(
    page,
    payload: dict[str, Any],
    workspace_name: str,
    batch: list[dict[str, Any]],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Anti-duplicacao: F5 na aba Files e checa quais arquivos do lote JA estao na workspace.

    Um lote "nao confirmado" (timeout) pode ter sido enviado de fato (falso negativo da
    confirmacao estrita). Antes de reenviar, recarregamos e lemos a workspace usando os
    mesmos leitores robustos do monitor (tratam o render incremental do Cloudscape, evitando
    falso "ausente"). Devolve (present_items, absent_items).

    Espelha a invariante do delete-verificado-por-F5: so reenvia o que REALMENTE nao esta la.
    Em qualquer falha da verificacao, devolve ([], batch) -> mantem o comportamento atual
    (isola o lote inteiro), sem mascarar a falha original.
    """
    # Import tardio: o monitor nao importa este modulo (sem ciclo), mas o import tardio
    # mantem o carregamento do modulo leve e blinda contra ordem de import.
    from app.services.playwright.playground_monitor import (
        FOUND_STATUSES,
        expected_file_name,
        f5_reopen_files,
        read_all_pages_statuses,
    )

    expected_names = [name for name in (expected_file_name(item) for item in batch) if name]
    if not expected_names:
        return [], list(batch)
    try:
        f5_reopen_files(page, payload, workspace_name, log, should_continue=should_continue)
        statuses = read_all_pages_statuses(page, expected_names, log, should_continue=should_continue)
    except Exception as exc:
        log(
            "warning",
            f"Verificacao de presenca na workspace falhou; tratando o lote como ausente: {exc}",
            metadata={"files": expected_names},
        )
        return [], list(batch)

    present: list[dict[str, Any]] = []
    absent: list[dict[str, Any]] = []
    for item in batch:
        name = expected_file_name(item)
        status = (statuses.get(name) or {}).get("status")
        if name and status in FOUND_STATUSES:
            present.append(item)
        else:
            absent.append(item)
    log(
        "info",
        "Verificacao de presenca na workspace concluida.",
        metadata={
            "present": [expected_file_name(i) for i in present],
            "absent": [expected_file_name(i) for i in absent],
        },
    )
    return present, absent


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


def dismiss_upload_complete_banner(page, log: Callable) -> bool:
    """Tenta fechar o flashbar/notificacao de "Upload complete" do Cloudscape que persiste
    apos a conclusao de um lote (banner verde com header "Uploading files" e subtext
    "Upload complete" + botao "View files" + botao "X" de fechar).

    O banner nao desaparece sozinho, e seu header "Uploading files" faz o snapshot pre-clique
    do proximo lote enxergar pre_active=True, bloqueando a Confirmacao B. Dispensar o banner
    aqui garante pre_active=False antes do snapshot.

    Seguranca:
    - So e chamado APOS a conclusao confirmada do lote anterior (nunca durante upload ativo).
    - best-effort: qualquer excecao e engolida; False indica que o banner nao foi encontrado
      ou nao foi possivel clica-lo (sem efeito colateral).
    - Verifica que o banner foi realmente dispensado (page_text nao contem mais o texto ativo)
      antes de retornar True.

    Retorna True se o banner foi dispensado, False se nao havia banner ou falhou (no-op seguro).
    """
    # Verificacao rapida: so tenta dispensar se a pagina realmente mostra o banner.
    try:
        body = page_text(page).lower()
        if not (_body_has_active(body) and _body_has_complete(body)):
            return False
    except Exception:
        return False

    # Estrategia 1 (prioritaria): JS direto no DOM.
    #
    # Percorre todos os elementos do Cloudscape Flashbar/notificacao e encontra o botao de
    # fechar pelo texto "x"/"×" ou pelo aria-label (em qualquer capitalizacao/idioma). Nao
    # depende de classes CSS com hash que mudam por build. O script JS:
    #   - Encontra todos os elementos visiveis que contem texto de conclusao de upload.
    #   - Dentro de cada um, procura o ultimo botao (o "X" sempre e o ultimo no Cloudscape).
    #   - Clica e retorna o texto do botao para log.
    _DISMISS_JS = """
(function() {
    var completionTexts = ['upload complete', 'uploaded', 'concluido', 'concluído'];
    var activeTexts     = ['uploading files', 'uploading file', 'enviando arquivos'];
    function hasText(el, texts) {
        var t = (el.innerText || el.textContent || '').toLowerCase();
        return texts.some(function(s) { return t.indexOf(s) !== -1; });
    }
    // Walk all visible elements that have both active and complete text (the banner container).
    var all = document.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.offsetParent && el.tagName !== 'BODY') continue;  // hidden
        if (!hasText(el, completionTexts)) continue;
        if (!hasText(el, activeTexts)) continue;
        // Found a container with both texts. Look for the dismiss/close button inside.
        var btns = el.querySelectorAll('button');
        if (!btns.length) continue;
        // Try aria-label first (multilingual).
        var dismissLabels = ['dismiss', 'close', 'fechar', 'dispensar', 'fermer', 'cerrar'];
        for (var j = 0; j < btns.length; j++) {
            var lbl = (btns[j].getAttribute('aria-label') || btns[j].getAttribute('title') || '').toLowerCase();
            if (dismissLabels.some(function(d) { return lbl.indexOf(d) !== -1; })) {
                btns[j].click();
                return 'aria-label:' + lbl;
            }
        }
        // Fallback: last button (Cloudscape places dismiss last, after "View files").
        var lastBtn = btns[btns.length - 1];
        // Only click if the button text is short (not "View files" etc.).
        var lastText = (lastBtn.innerText || lastBtn.textContent || '').trim();
        if (lastText.length <= 5) {
            lastBtn.click();
            return 'last-btn:' + lastText;
        }
        // Second-to-last if last text is long.
        if (btns.length >= 2) {
            var prevBtn = btns[btns.length - 2];
            var prevText = (prevBtn.innerText || prevBtn.textContent || '').trim();
            if (prevText.length <= 5) {
                prevBtn.click();
                return 'prev-btn:' + prevText;
            }
        }
    }
    return null;
})()
"""
    try:
        result = page.evaluate(_DISMISS_JS)
        if result is not None:
            time.sleep(0.5)
            after_body = page_text(page).lower()
            if not _body_has_active(after_body):
                log(
                    "info",
                    "Banner de conclusao de upload dispensado (JS direto).",
                    metadata={"clicked": str(result)},
                )
                return True
            # JS clicou mas banner permanece; cai para estrategia Playwright.
            log(
                "info",
                "JS clicou no botao do banner mas indicador ainda presente; tentando via Playwright.",
                metadata={"js_result": str(result)},
            )
    except Exception:
        pass

    # Estrategia 2: Playwright — rotulos acessiveis de DISMISS_BANNER_TEXTS (multilingue).
    for t in DISMISS_BANNER_TEXTS:
        for lookup in (
            lambda t=t: page.get_by_role("button", name=t, exact=True),
            lambda t=t: page.get_by_role("button", name=t, exact=False),
            lambda t=t: page.locator(f"button[aria-label='{t}']"),
            lambda t=t: page.locator(f"button[title='{t}']"),
        ):
            try:
                btn = lookup()
                if not btn.count():
                    continue
                candidate = btn.first
                if not candidate.is_visible(timeout=300) or not candidate.is_enabled(timeout=300):
                    continue
                candidate.click(timeout=3000)
                time.sleep(0.5)
                if not _body_has_active(page_text(page).lower()):
                    log(
                        "info",
                        "Banner de conclusao de upload dispensado (Playwright por rotulo).",
                        metadata={"dismiss_label": t},
                    )
                    return True
            except Exception:
                continue

    # Estrategia 3: procura dentro de containers visiveis com texto de conclusao.
    flashbar_container_selectors = [
        "[class*='awsui_flash']",
        "[class*='awsui_notification']",
        "[role='status']",
        "[role='alert']",
    ]
    for container_sel in flashbar_container_selectors:
        try:
            containers = page.locator(container_sel)
            count = min(containers.count(), 10)
        except Exception:
            continue
        for ci in range(count):
            container = containers.nth(ci)
            try:
                if not container.is_visible(timeout=300):
                    continue
                container_text = (container.inner_text(timeout=500) or "").lower()
                if not _body_has_complete(container_text):
                    continue
            except Exception:
                continue
            # Tenta pelo CSS de classe dismiss (Cloudscape v3) e pelo ultimo botao.
            dismiss_lookups: list = [
                lambda: container.locator("button[class*='dismiss']"),
                lambda: container.locator("button[class*='awsui_dismiss']"),
                lambda: container.locator("button[class*='close']"),
                lambda: container.locator("button[class*='awsui_close']"),
                lambda: container.locator("button").filter(has_text="×"),
                lambda: container.locator("button").filter(has_text="✕"),
                lambda: container.locator("button").last,
            ]
            for lookup in dismiss_lookups:
                try:
                    btn = lookup()
                    if not btn.count():
                        continue
                    candidate = btn.first
                    if not candidate.is_visible(timeout=300) or not candidate.is_enabled(timeout=300):
                        continue
                    btn_text = (candidate.inner_text(timeout=300) or "").strip()
                    if len(btn_text) > 20:
                        continue
                    candidate.click(timeout=3000)
                    time.sleep(0.5)
                    if not _body_has_active(page_text(page).lower()):
                        log(
                            "info",
                            "Banner de conclusao de upload dispensado (container Playwright).",
                            metadata={"container_selector": container_sel, "btn_text": btn_text},
                        )
                        return True
                except Exception:
                    continue

    # Nenhuma estrategia teve sucesso — no-op seguro.
    return False


def wait_for_upload_ui_settled(
    page,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    *,
    timeout_seconds: float = 15,
) -> None:
    """Aguarda a UI de upload retornar ao estado neutro (sem indicador ativo "Uploading Files").

    Utilizado entre lotes intermediarios para garantir que o snapshot pre-clique do proximo
    lote nao enxergue o verde do lote anterior — o que bloquearia a Confirmacao B e tornaria
    o envio dependente unicamente da captura de rede.

    Estrategia em dois passos:
      1. Dispensa o flashbar/banner de "Upload complete" do Cloudscape (se presente). Esse
         banner persiste indefinidamente com o header "Uploading files" + subtext "Upload
         complete", impedindo que o loop de estabilizacao abaixo detecte a ausencia do verde.
         A dispensa e best-effort e nao fatal.
      2. Aguarda ate timeout_seconds o desaparecimento estavel do indicador "Uploading Files"
         (usando UPLOAD_COMPLETE_STABLE_SECONDS sem duplicar a logica). Se o timeout expirar
         sem estabilizar, apenas registra aviso e segue (nao e fatal; a confirmacao continua
         valida pela captura de rede se o verde persistir por razao espuria).
    """
    # Passo 1: tenta dispensar o banner de conclusao para limpar o verde pre-existente.
    try:
        dismiss_upload_complete_banner(page, log)
    except Exception:
        pass  # best-effort: nunca deve propagar

    deadline = time.monotonic() + timeout_seconds
    absent_since: float | None = None
    log("info", "Aguardando UI de upload retornar ao estado neutro antes do proximo lote.")
    while time.monotonic() < deadline:
        check_continue(should_continue)
        body = page_text(page).lower()
        if _body_has_active(body):
            absent_since = None
        else:
            if absent_since is None:
                absent_since = time.monotonic()
            elif time.monotonic() - absent_since >= UPLOAD_COMPLETE_STABLE_SECONDS:
                log("info", "UI de upload em estado neutro; prosseguindo ao proximo lote.")
                return
        time.sleep(0.5)
    log(
        "warning",
        "Indicador de upload ainda presente apos aguardar a UI estabilizar; "
        "prosseguindo mesmo assim (confirmacao de envio continua ativa).",
        metadata={"timeout_seconds": timeout_seconds},
    )


def _url_looks_like_upload(url: str) -> bool:
    """Heuristica: a URL parece ser um endpoint de upload de arquivo."""
    return bool(_UPLOAD_URL_PATTERN.search(url))


# Content-types que indicam um upload REAL de arquivo pelo navegador:
#  - multipart/form-data: form padrao do navegador carregando um arquivo;
#  - application/octet-stream e mimes de arquivo (pdf/office/imagem/...): PUT direto
#    (S3/blob) com o conteudo bruto do arquivo no corpo.
# As chamadas de API/telemetria de fundo do Playground (polling de status, fetch de dados
# do workspace) usam application/json / urlencoded e NAO devem confirmar o envio — eram a
# causa do falso positivo "clica Upload Files e finaliza sem enviar nenhum arquivo".
_FILE_UPLOAD_CONTENT_TYPES = (
    "multipart/form-data",
    "application/octet-stream",
    "application/pdf",
    "application/msword",
    "application/vnd",
    "application/zip",
    "image/",
    "video/",
    "audio/",
)


def _request_content_type(request) -> str:
    try:
        headers = request.headers or {}
    except Exception:
        return ""
    return (headers.get("content-type") or "").lower()


def _request_is_file_upload(request) -> bool:
    """True quando a requisicao realmente carrega o conteudo de um arquivo (multipart/binario).

    Distingue o upload REAL das chamadas de fundo (JSON/urlencoded) que tambem batem no
    _UPLOAD_URL_PATTERN — sem essa checagem, um POST de polling para `/.../files` confirmava
    o envio de forma precoce, antes mesmo do verde "Uploading Files" surgir.
    """
    content_type = _request_content_type(request)
    if not content_type:
        return False
    return any(token in content_type for token in _FILE_UPLOAD_CONTENT_TYPES)


class _NetworkCapture:
    """Registra requisicoes POST/PUT disparadas apos o clique de upload.

    Uso:
        capture = _NetworkCapture(page, log)
        capture.start()
        # ... clique de upload ...
        confirmed, detail = capture.wait_for_upload_response(timeout_seconds)
        capture.stop()
    """

    def __init__(self, page, log: Callable) -> None:
        self._page = page
        self._log = log
        self._requests: list[dict[str, str]] = []   # {method, url, status}
        self._confirmed = False
        self._confirmed_url = ""
        self._lock = __import__("threading").Lock()
        self._on_response_handler = None

    def _on_response(self, response) -> None:
        try:
            request = response.request
            method = (request.method or "").upper()
            url = response.url or ""
            status = response.status
            if method not in ("POST", "PUT", "PATCH"):
                return
            content_type = _request_content_type(request)
            is_file_upload = _request_is_file_upload(request)
            entry = {
                "method": method,
                "url": url,
                "status": str(status),
                "content_type": content_type,
                "file_upload": str(is_file_upload),
            }
            with self._lock:
                self._requests.append(entry)
                # So confirma o envio quando a resposta 2xx for de uma URL de upload E a
                # requisicao realmente carregar o conteudo de um arquivo (multipart/binario).
                # Chamadas de fundo (JSON) ficam de fora -> o verde "Uploading Files" decide.
                if (
                    status
                    and 200 <= int(status) < 300
                    and _url_looks_like_upload(url)
                    and is_file_upload
                    and not self._confirmed
                ):
                    self._confirmed = True
                    self._confirmed_url = url
        except Exception:
            pass

    def start(self) -> None:
        self._on_response_handler = self._on_response
        self._page.on("response", self._on_response_handler)

    def stop(self) -> None:
        try:
            if self._on_response_handler:
                self._page.remove_listener("response", self._on_response_handler)
        except Exception:
            pass

    def wait_for_upload_response(self, timeout_seconds: float) -> tuple[bool, str]:
        """Aguarda ate timeout_seconds por uma resposta 2xx em URL de upload.

        Retorna (confirmado, url_confirmada).
        """
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self._lock:
                if self._confirmed:
                    return True, self._confirmed_url
            time.sleep(0.3)
        with self._lock:
            return self._confirmed, self._confirmed_url

    def all_requests(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._requests)


def wait_for_batch_sent(
    page,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    *,
    pre_click_body: str = "",
    network_capture: "_NetworkCapture | None" = None,
    task_id: int = 0,
    batch: "list[dict[str, Any]] | None" = None,
) -> None:
    """Aguarda confirmacao REAL de que o lote foi enviado ao servidor.

    Confirma o envio por QUALQUER um destes sinais reais (os arquivos ja foram
    verificados como anexados aos inputs em choose_files, sinal 1):
      A. Rede: uma requisicao POST/PUT/PATCH para uma URL de upload retornou 2xx
         (capturada pelo _NetworkCapture iniciado ANTES do clique). Sinal mais forte.
      B. Verde "Uploading Files" que SURGE apos o clique (nao estava no snapshot
         pre-clique). Cobre o caso de a URL de upload nao casar o padrao de rede,
         sem reintroduzir falso positivo (verde pre-existente NAO conta).

    NUNCA confirma por texto de "concluido" isolado (era a causa do retorno precoce
    sem envio); verde PRE-EXISTENTE tambem nao conta.

    Levanta UploadFailed("uploading error") ao detectar o vermelho.
    Levanta UploadFailed com diagnostico completo se nenhum sinal real chegar dentro
    de BATCH_SENT_TIMEOUT_SECONDS.
    """
    deadline = time.monotonic() + BATCH_SENT_TIMEOUT_SECONDS

    # Textos de conclusao pre-existentes (ignora como sinal deste lote).
    pre_complete_tokens = {text.lower() for text in UPLOAD_COMPLETE_TEXTS if text.lower() in pre_click_body}
    if pre_complete_tokens:
        log(
            "info",
            "Snapshot pre-clique contem textos de conclusao; nao contam como sinal deste lote.",
            metadata={"pre_complete_tokens": sorted(pre_complete_tokens)},
        )

    # Verde "Uploading Files" ja presente ANTES do clique nao conta como sinal deste lote;
    # so um verde que SURGE depois do clique confirma o envio (arquivos ja anexados, sinal 1).
    pre_active = any(text.lower() in pre_click_body for text in UPLOAD_ACTIVE_TEXTS)

    saw_active_text = False
    network_confirmed = False
    confirmed_url = ""

    while time.monotonic() < deadline:
        check_continue(should_continue)
        body = page_text(page).lower()

        # Erro vermelho: prioridade maxima, independe de sinal de rede.
        if any(text.lower() in body for text in UPLOAD_ERROR_TEXTS):
            raise UploadFailed("uploading error")

        # Verificar sinal de rede (sinal primario 1).
        if network_capture and not network_confirmed:
            with network_capture._lock:
                network_confirmed = network_capture._confirmed
                confirmed_url = network_capture._confirmed_url

        # Verde "Uploading Files": registra deteccao; confirma so se SURGIU apos o clique.
        active_now = _body_has_active(body)
        if active_now and not saw_active_text:
            log("info", "Uploading Files (verde) detectado na tela.")
            saw_active_text = True

        # CONFIRMACAO A: rede (POST/PUT/PATCH 2xx em endpoint de upload). Sinal mais forte.
        if network_confirmed:
            log(
                "info",
                "Upload confirmado por sinal de rede (POST/PUT 2xx).",
                metadata={"confirmed_url": confirmed_url, "text_active": saw_active_text},
            )
            return

        # CONFIRMACAO B: verde "Uploading Files" que SURGIU apos o clique (nao estava no
        # snapshot pre-clique). Com os arquivos ja anexados (sinal 1), e envio real; cobre
        # o caso de a URL de upload nao casar o padrao de rede, sem falso positivo.
        if active_now and not pre_active:
            log("info", "Uploading Files (verde) surgiu apos o clique; envio confirmado.")
            return

        # Sem captura de rede (isolamento 1-a-1): aceita novo token de conclusao pos-clique.
        if network_capture is None:
            new_complete_tokens = {
                text.lower()
                for text in UPLOAD_COMPLETE_TEXTS
                if text.lower() in body and text.lower() not in pre_complete_tokens
            }
            if new_complete_tokens:
                log(
                    "info",
                    "Upload concluido diretamente (novo texto de conclusao, sem captura de rede).",
                    metadata={"new_complete_tokens": sorted(new_complete_tokens)},
                )
                return

        time.sleep(0.4)

    # --- Timeout: nenhum sinal real confirmou o envio ---
    # Diagnostico completo antes de levantar.
    body_final = page_text(page)
    attached_count = _count_files_in_inputs(page)
    captured_requests = network_capture.all_requests() if network_capture else []

    log(
        "error",
        "Upload NAO confirmado no tempo limite: nenhum sinal real de envio detectado.",
        metadata={
            "timeout_seconds": BATCH_SENT_TIMEOUT_SECONDS,
            "network_capture_active": network_capture is not None,
            "network_confirmed": network_confirmed,
            "saw_active_text": saw_active_text,
            "attached_count_at_timeout": attached_count,
            "post_put_requests_captured": captured_requests,
            "body_sample": body_final[:600],
            "batch_files": [i.get("file_name") for i in (batch or [])],
        },
    )
    safe_error_screenshot(page, task_id, log)

    if body_has_upload_error(page):
        raise UploadFailed("uploading error")
    raise UploadFailed(
        f"Lote nao confirmado como enviado em {BATCH_SENT_TIMEOUT_SECONDS}s: "
        f"rede={'confirmada' if network_confirmed else 'sem resposta 2xx'}, "
        f"texto_verde={'sim' if saw_active_text else 'nao'}, "
        f"arquivos_no_input={attached_count}. "
        "Veja logs 'post_put_requests_captured' e screenshot para diagnostico."
    )


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
        # Prioridade para o status de conclusao (evita loop se o titulo continuar sendo "Uploading files")
        if has_complete:
            log("info", "Lote concluido com sucesso (texto de conclusao detectado).")
            return
        elif has_active:
            saw_active = True
            absent_since = None
        elif saw_active:
            if absent_since is None:
                absent_since = time.monotonic()
            elif time.monotonic() - absent_since >= UPLOAD_COMPLETE_STABLE_SECONDS:
                log("info", "Lote concluido com sucesso (indicador de envio desapareceu).")
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
            # 1) Mira o SUBMIT real primeiro (type=submit exclui a ABA 'Upload Files' e o link do
            #    Workspace) — confirmado pelo DOM ao vivo do Add Data.
            for factory in final_upload_submit_locators(page):
                if click_final_upload_candidate(factory(), log):
                    return
            # 2) Fallback por texto (UIs diferentes), excluindo a aba de tabs para nao clica-la.
            for text in UPLOAD_FILES_TEXTS:
                lookups = [
                    lambda text=text: page.locator(f"button:has-text('{text}'):not([class*='tabs-tab'])"),
                    lambda text=text: page.locator(f"[role='button']:has-text('{text}'):not([class*='tabs-tab'])"),
                    lambda text=text: page.get_by_role("button", name=text),
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
    task_id: int = 0,
    batch_index: int = 0,
) -> list[dict[str, Any]]:
    """Envia um lote (pasta) na tela de upload ja aberta.

    Fluxo: garante a area de Choose Files aberta (sem recarregar), verifica que os
    arquivos foram realmente anexados aos inputs (sinal 1), registra captura de rede
    ANTES do clique (sinal 2), clica no Upload Files final e aguarda confirmacao real
    de envio (requisicao POST/PUT 2xx para URL de upload).

    Nunca declara "enviado" sem pelo menos um sinal real (rede OU verde de texto quando
    a captura de rede nao esta disponivel). Se nenhum sinal chegar, levanta UploadFailed
    com diagnostico completo (screenshot + contagem de inputs + requisicoes capturadas).

    No ultimo lote (is_last_batch=True), fecha o Chromium logo apos a confirmacao sem
    aguardar conclusao total (decisao registrada do usuario).

    batch_index: indice zero-based do lote dentro da sequencia geral. Para o primeiro lote
    (batch_index=0) nao ha espera de estabilizacao; para lotes subsequentes (batch_index>0)
    aguarda a UI neutralizar o verde do lote anterior antes de tirar o snapshot pre-clique.
    """
    paths = [str(Path(item["path"]).resolve()) for item in batch]
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        raise UploadFailed(f"Arquivo(s) nao encontrado(s): {missing}")
    check_continue(should_continue)

    # FIX: Para lotes 2+ aguarda a UI retornar ao estado neutro (sem o verde "Uploading
    # Files" do lote anterior) antes de prosseguir. Sem isso, pre_active ficaria True e a
    # Confirmacao B (verde que SURGE apos o clique) ficaria permanentemente bloqueada,
    # deixando o envio dependente apenas da captura de rede — e qualquer falha de rede
    # esgotaria o BATCH_SENT_TIMEOUT_SECONDS mesmo com o upload tendo ocorrido de fato.
    if batch_index > 0:
        wait_for_upload_ui_settled(page, log, should_continue)

    ensure_upload_area_open(page, log)
    check_continue(should_continue)
    # choose_files ja verifica a contagem real de arquivos nos inputs via JS (sinal 1).
    choose_files(page, paths, log)
    check_continue(should_continue)
    wait_for_selected_files(page, batch, log, should_continue=should_continue)

    # Snapshot do body ANTES do clique: textos de conclusao pre-existentes nao contam
    # como evidencia de que ESTE lote iniciou o envio. Com wait_for_upload_ui_settled
    # executado acima (lotes 2+), o verde do lote anterior ja desapareceu, garantindo
    # pre_active=False e desbloqueando a Confirmacao B para este lote.
    pre_click_body = page_text(page).lower()

    # Inicia captura de rede ANTES do clique para registrar todas as requisicoes
    # POST/PUT disparadas em consequencia do botao Upload Files (sinal 2).
    capture = _NetworkCapture(page, log)
    capture.start()
    try:
        click_final_upload_with_recovery(page, log, should_continue=should_continue)

        # Aguarda confirmacao real de envio: rede (primario) ou texto verde (fallback).
        wait_for_batch_sent(
            page,
            log,
            should_continue=should_continue,
            pre_click_body=pre_click_body,
            network_capture=capture,
            task_id=task_id,
            batch=batch,
        )
    finally:
        capture.stop()

    log("info", "Aguardando a tela verde de conclusao do lote...")
    wait_for_batch_complete(page, log, should_continue=should_continue)

    if is_last_batch:
        time.sleep(3)
        log("info", "Confirmacao de upload recebida. Todos os lotes foram enviados com sucesso.")
    else:
        log("info", "Lote concluido com sucesso; seguindo ao proximo lote na mesma tela.")
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


def _rebatch_healthy(
    page,
    items: list[dict[str, Any]],
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    on_file_error: Callable | None,
    should_continue: Callable[[], bool] | None = None,
    *,
    task_id: int = 0,
) -> list[dict[str, Any]]:
    """Reagrupa os arquivos restantes em sub-lotes normais apos o culpado ter sido isolado.

    Utiliza upload_batch com batch_index=1 (obrigatorio: a pagina tem atividade/verde do
    isolamento anterior, portanto wait_for_upload_ui_settled deve rodar antes do snapshot
    pre-clique). Confirma o envio pelos mesmos sinais reais que o caminho principal
    (_NetworkCapture 2xx + verde pos-clique); nunca enfraquece a logica de confirmacao.

    Se um sub-lote falhar com suspeita de corrupcao (segundo arquivo corrompido oculto no
    restante), cai para isolate_one_by_one apenas nesse sub-lote — a recursao e limitada
    porque cada chamada de isolate_one_by_one remove pelo menos um corrompido antes de
    invocar _rebatch_healthy novamente sobre um conjunto estritamente menor.
    """
    results: list[dict[str, Any]] = []
    batch_size = max(1, int(payload.get("batch_size") or settings.UPLOAD_BATCH_SIZE))
    sub_batches = chunked(items, batch_size)
    total = len(sub_batches)
    for i, sub_batch in enumerate(sub_batches, start=1):
        check_continue(should_continue)
        log(
            "info",
            f"Reenvio em lote pos-isolamento: sub-lote {i}/{total} com {len(sub_batch)} arquivo(s).",
            metadata={"files": [item.get("file_name") for item in sub_batch]},
        )
        try:
            results.extend(
                upload_batch(
                    page,
                    sub_batch,
                    log,
                    should_continue=should_continue,
                    is_last_batch=False,
                    task_id=task_id,
                    batch_index=1,
                )
            )
        except UploadFailed as exc:
            if not is_corruption_suspect(exc):
                raise
            log(
                "warning",
                f"Reenvio em lote pos-isolamento falhou (sub-lote {i}); aplicando isolamento 1-a-1 novamente neste sub-lote.",
                metadata={"files": [item.get("file_name") for item in sub_batch]},
            )
            try:
                recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
            except Exception:
                pass
            results.extend(
                isolate_one_by_one(page, sub_batch, payload, workspace_name, log, on_file_error, should_continue, task_id=task_id)
            )
    return results


def isolate_one_by_one(
    page,
    batch: list[dict[str, Any]],
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    on_file_error: Callable | None,
    should_continue: Callable[[], bool] | None = None,
    *,
    task_id: int = 0,
) -> list[dict[str, Any]]:
    """Fallback robusto: reenvia cada arquivo do lote individualmente para isolar os corrompidos.

    Ao encontrar o primeiro culpado, reagrupa os arquivos restantes em sub-lotes normais via
    _rebatch_healthy (mais eficiente do que continuar 1-a-1 para arquivos saudaveis).
    Nunca move um arquivo saudavel: so confirma corrompido o arquivo que falha sozinho.
    """
    corrupted_items: list[dict[str, Any]] = []
    healthy_results: list[dict[str, Any]] = []
    try:
        recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
    except Exception as recovery_exc:
        log("warning", "Recuperacao da area de upload falhou antes do isolamento individual.", metadata={"error": str(recovery_exc)})
    batch_list = list(batch)
    for idx, solo_item in enumerate(batch_list):
        check_continue(should_continue)
        try:
            healthy_results.extend(upload_batch(page, [solo_item], log, should_continue=should_continue, task_id=task_id))
            log("info", f"Arquivo revalidado individualmente com sucesso: {solo_item.get('file_name')}")
        except UploadFailed as solo_exc:
            # Um arquivo sozinho que falha (vermelho OU lote nao confirmado/timeout) e o
            # culpado: vai para ERROR. So re-levanta falhas que nao sejam suspeita de
            # corrupcao, para nao mascarar problemas reais de UI/sessao.
            if not is_corruption_suspect(solo_exc):
                raise
            corrupted_items.append(solo_item)
            log("warning", f"Arquivo confirmado como corrompido: {solo_item.get('file_name')}", metadata={"file_name": solo_item.get("file_name")})
            remaining_unprobed = batch_list[idx + 1:]
            if remaining_unprobed:
                log(
                    "info",
                    f"Arquivo corrompido isolado; reagrupando {len(remaining_unprobed)} arquivo(s) restante(s) para reenvio em lote normal.",
                    metadata={"files": [item.get("file_name") for item in remaining_unprobed]},
                )
                try:
                    recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
                except Exception:
                    pass
                healthy_results.extend(
                    _rebatch_healthy(page, remaining_unprobed, payload, workspace_name, log, on_file_error, should_continue, task_id=task_id)
                )
            # Culpado encontrado e restante tratado: encerra o loop 1-a-1.
            break
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
    *,
    task_id: int = 0,
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
            result = upload_batch(page, remainder, log, should_continue=should_continue, task_id=task_id)
            finalize_corrupted([candidate], log, on_file_error)
            return result
        except UploadFailed as exc:
            # Restante ainda falhou (vermelho OU lote nao confirmado/timeout): a identificacao
            # do candidato pelo fast-path nao foi suficiente; cai para o isolamento 1 a 1.
            if not is_corruption_suspect(exc):
                raise
            log("warning", f"Reenvio do restante do lote {batch_number} ainda deu erro; caindo para o isolamento 1 a 1.", metadata={"candidate": candidate_name})
            try:
                recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
            except Exception:
                pass

    return isolate_one_by_one(page, batch, payload, workspace_name, log, on_file_error, should_continue, task_id=task_id)


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
                    # Sem recarregar entre lotes: apos o lote anterior concluir, seguimos
                    # direto ao Choose Files do proximo lote na mesma tela. O ultimo lote
                    # aguarda a conclusao total. batch_index (0-based) permite que
                    # upload_batch aguarde a UI estabilizar antes do snapshot pre-clique
                    # em lotes intermediarios (ver wait_for_upload_ui_settled).
                    batch_result = upload_batch(
                        page,
                        batch,
                        log,
                        should_continue=should_continue,
                        is_last_batch=(index == len(batches)),
                        task_id=task_id,
                        batch_index=(index - 1),
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
                    # Roteia para o isolamento de corrompido tanto o vermelho explicito
                    # ("uploading error") quanto o timeout de confirmacao ("lote nao
                    # confirmado") — este ultimo e o sintoma do arquivo-lixo (ex.: lock
                    # do Office '~$...docx'). Sem isto, o lote inteiro morria por causa de
                    # um unico corrompido em vez de isola-lo na pasta ERROR.
                    if not is_corruption_suspect(exc):
                        raise
                    if not batch:
                        raise
                    # Screenshot de diagnostico antes de qualquer operacao de recuperacao/IO.
                    error_screenshot_saved = save_recovery_screenshot(browser, task_id, log)
                    log(
                        "warning",
                        f"Falha de envio no lote {batch_number} (Upload Error ou lote nao confirmado); identificando o arquivo corrompido (modo hibrido).",
                        metadata={"batch": batch_number, "files": [i.get("file_name") for i in batch]},
                    )
                    # ANTI-DUPLICACAO: o lote pode ter sido enviado de fato (falso negativo
                    # da confirmacao). Verifica na workspace (F5) ANTES de reenviar e so
                    # isola/reenvia o que REALMENTE esta ausente -- evita duplicar (lote + 1-a-1).
                    present, absent = verify_batch_present_in_workspace(
                        page, payload, workspace_name, batch, log, should_continue=should_continue
                    )
                    batch_result = uploaded_results(present) if present else []
                    if present:
                        log(
                            "warning",
                            f"Lote {batch_number} nao confirmou no tempo, mas {len(present)} arquivo(s) "
                            "ja constam na workspace; nao serao reenviados (evita duplicar).",
                            metadata={"already_present": [i.get("file_name") for i in present]},
                        )
                    if absent:
                        # A verificacao navegou para a aba Files: reabre a area de upload antes de isolar.
                        try:
                            recover_upload_area_in_same_session(page, payload, workspace_name, log, should_continue=should_continue)
                        except Exception as recovery_exc:
                            log("warning", "Recuperacao da area de upload apos verificacao falhou.", metadata={"error": str(recovery_exc)})
                        # Modo hibrido: tenta pelo ultimo/destacado e cai para 1-a-1 se ambiguo.
                        # Nao usa 'break': cai no checkpoint abaixo para registrar os saudaveis.
                        batch_result = batch_result + handle_uploading_error(
                            page,
                            absent,
                            batch_number,
                            payload,
                            workspace_name,
                            log,
                            on_file_error,
                            should_continue=should_continue,
                            task_id=task_id,
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
                    "Lote concluido; aguardando UI estabilizar antes do proximo lote na mesma sessao do Chromium.",
                    metadata={"next_batch": int(batches[index][0].get("batch_number") or (index + 1))},
                )
        if browser:
            close_browser(browser, log, "Todos os lotes enviados. Fechando o navegador.")
            browser = None
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


# WORD_COM_EXTENSIONS / EXCEL_COM_EXTENSIONS / POWERPOINT_COM_EXTENSIONS sao definidas no
# topo do modulo (compoem SUPPORTED_OFFICE_EXTENSIONS) e usadas em _office_kind_for abaixo.

# Script PowerShell que dirige o Office (Word/Excel/PowerPoint) por COM e exporta para PDF.
# Os caminhos chegam por variaveis de ambiente (HUB_SRC/HUB_DST/HUB_KIND) para evitar
# problemas de aspas/escape e injecao. Roda via -EncodedCommand, que NAO esbarra na
# ExecutionPolicy de arquivos .ps1 (comum em notebooks corporativos travados).
_OFFICE_COM_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$src = $env:HUB_SRC
$dst = $env:HUB_DST
$kind = $env:HUB_KIND
# Modo recuperacao: reabre arquivos corrompidos usando os mecanismos nativos do Office
# (Word OpenAndRepair / Excel CorruptLoad). $m preenche os parametros opcionais do meio.
$repair = ($env:HUB_REPAIR -eq '1')
$m = [System.Reflection.Missing]::Value
$app = $null
$newpid = $null
# Nome do processo do Office por tipo -> usado p/ rastrear SO a instancia que ESTE script criar
# (nao mexe no Word/Excel que o usuario ja tenha aberto). O PID novo e gravado no HUB_PIDFILE
# ANTES do Open/Export (que pode travar), para o Python conseguir matar o orfao mesmo se o
# PowerShell for encerrado no timeout.
$procName = @{ 'word' = 'WINWORD'; 'excel' = 'EXCEL'; 'powerpoint' = 'POWERPNT' }[$kind]
$before = @()
if ($procName) { $before = @(Get-Process -Name $procName -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id) }
function Save-NewOfficePid {
    $after = @(Get-Process -Name $procName -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $delta = @($after | Where-Object { $_ -notin $before })
    if ($delta.Count -eq 1) {
        if ($env:HUB_PIDFILE) { try { Set-Content -Path $env:HUB_PIDFILE -Value $delta[0] -Encoding ascii } catch {} }
        return $delta[0]
    }
    return $null
}
try {
    if ($kind -eq 'word') {
        $app = New-Object -ComObject Word.Application
        $app.Visible = $false
        $app.DisplayAlerts = 0
        $newpid = Save-NewOfficePid
        if ($repair) {
            # OpenAndRepair = 13o parametro de Documents.Open.
            $doc = $app.Documents.Open($src,$false,$true,$false,$m,$m,$m,$m,$m,$m,$m,$m,$true)
        } else {
            $doc = $app.Documents.Open($src, $false, $true, $false)
        }
        $doc.ExportAsFixedFormat($dst, 17)   # wdExportFormatPDF = 17
        $doc.Close($false)                   # wdDoNotSaveChanges = 0
    } elseif ($kind -eq 'excel') {
        $app = New-Object -ComObject Excel.Application
        $app.Visible = $false
        $app.DisplayAlerts = $false
        $newpid = Save-NewOfficePid
        if ($repair) {
            # CorruptLoad = 15o parametro: 1=xlRepairFile (reparar), 2=xlExtractData (extrair dados).
            try {
                $wb = $app.Workbooks.Open($src,0,$true,$m,$m,$m,$m,$m,$m,$m,$m,$m,$m,$m,1)
            } catch {
                $wb = $app.Workbooks.Open($src,0,$true,$m,$m,$m,$m,$m,$m,$m,$m,$m,$m,$m,2)
            }
        } else {
            $wb = $app.Workbooks.Open($src, 0, $true)
        }
        $wb.ExportAsFixedFormat(0, $dst)     # xlTypePDF = 0
        $wb.Close($false)
    } elseif ($kind -eq 'powerpoint') {
        # PowerPoint nao expoe API de reparo no COM; abre normal (recuperacao fica com o LibreOffice).
        $app = New-Object -ComObject PowerPoint.Application
        $newpid = Save-NewOfficePid
        $pres = $app.Presentations.Open($src, $true, $false, $false)  # ReadOnly, Untitled, sem janela
        $pres.SaveAs($dst, 32)               # ppSaveAsPDF = 32
        $pres.Close()
    } else {
        throw "kind invalido: $kind"
    }
} finally {
    if ($app -ne $null) { try { $app.Quit() } catch {} }
    # Libera a referencia COM e, se a instancia que criamos sobrou (travou/erro), encerra SO ela.
    try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) } catch {}
    if ($newpid) { try { Stop-Process -Id $newpid -Force -ErrorAction SilentlyContinue } catch {} }
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


_OFFICE_PROCESS_NAMES = ("WINWORD.EXE", "EXCEL.EXE", "POWERPNT.EXE")


def _kill_tracked_office_process(pidfile: Path, log: Callable) -> None:
    """Encerra SO o processo do Office que esta conversao criou (PID gravado no pidfile pelo PS).

    Nunca enumera/mata todos os Office -> o Word/Excel que o USUARIO abriu fica intacto. Antes de
    matar, confere pelo `tasklist` que o PID ainda e um processo do Office (evita PID reciclado) e
    que ele ainda existe (se o Quit funcionou, ja saiu -> no-op). Usado apos timeout/erro para nao
    deixar instancias orfas travadas segurando o arquivo aberto (causa do "muitos Word abertos").
    """
    if os.name != "nt":
        return
    try:
        pid = int(pidfile.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return
    if pid <= 0:
        return
    try:
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
        ).stdout or ""
    except Exception:
        return
    lowered = listing.lower()
    if not any(name.lower() in lowered for name in _OFFICE_PROCESS_NAMES):
        return  # ja saiu (Quit ok) ou o PID nao e mais do Office -> nada a fazer
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=15)
        log("warning", f"Instancia orfa do Office (PID {pid}) encerrada apos travar na conversao PDF.")
    except Exception:
        pass


def convert_office_via_com(source: Path, target_pdf: Path, log: Callable, repair: bool = False) -> bool:
    """Converte para PDF via Microsoft Office (COM) usando PowerShell. True se gerou o PDF.

    Usa o Office ja instalado na maquina (Word/Excel/PowerPoint): funciona offline, nao exige
    LibreOffice e nao adiciona dependencia Python. Em maquina sem Windows ou com formato fora
    do Office, retorna False para o chamador cair no LibreOffice.

    repair=True reabre o arquivo em modo de recuperacao (Word OpenAndRepair / Excel
    CorruptLoad) para tentar salvar arquivos corrompidos antes de desistir.

    Limpeza: o PS grava o PID da instancia que criou; se a conversao travar/estourar o timeout, a
    instancia orfa e encerrada aqui no `finally` (o Python mata o Office que o COM abriu, que NAO e
    filho do PowerShell) -- sem tocar em nenhum Office aberto pelo usuario.
    """
    if os.name != "nt":
        return False
    kind = office_com_kind(source.suffix)
    if not kind:
        return False
    encoded = base64.b64encode(_OFFICE_COM_PS_SCRIPT.encode("utf-16-le")).decode("ascii")
    pidfile = Path(tempfile.gettempdir()) / f"hub_office_pid_{os.getpid()}_{time.time_ns()}.txt"
    env = {**os.environ, "HUB_SRC": str(source), "HUB_DST": str(target_pdf), "HUB_KIND": kind, "HUB_PIDFILE": str(pidfile)}
    if repair:
        env["HUB_REPAIR"] = "1"
    mode = " (modo recuperacao)" if repair else ""
    log("info", f"Conversao PDF via Microsoft Office ({kind}){mode} iniciada.")
    try:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
        except subprocess.TimeoutExpired:
            log("warning", f"Conversao via Office (COM) estourou 180s ({kind}); encerrando a instancia travada.")
            return False
        except Exception as exc:
            log("warning", f"Conversao via Office (COM) nao executou: {exc}")
            return False
        if result.returncode == 0 and target_pdf.exists():
            return True
        detail = (result.stderr or result.stdout or "").strip()
        log("warning", f"Conversao via Office (COM) nao concluiu ({kind}): {detail[:500] or 'sem detalhe'}")
        return False
    finally:
        # Roda em TODOS os caminhos (sucesso, falha, timeout): mata o orfao se sobrou e apaga o pidfile.
        _kill_tracked_office_process(pidfile, log)
        try:
            pidfile.unlink()
        except OSError:
            pass


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
    # Guarda de colisao: dois arquivos de mesmo nome-base e extensoes diferentes (ex.:
    # relatorio.docx e relatorio.xls) no mesmo pdf_dir gerariam o mesmo relatorio.pdf e um
    # sobrescreveria o outro silenciosamente. Sufixa com timestamp quando ja existe.
    if pdf_path.exists():
        pdf_path = target_dir / f"{source.stem}_{int(time.time() * 1000)}.pdf"
    log("info", "Conversao PDF iniciada.")

    # 1) Microsoft Office (COM): usa o Office ja instalado, offline e sem LibreOffice.
    if convert_office_via_com(source, pdf_path, log):
        log("info", f"PDF criado via Microsoft Office: {pdf_path}")
        return str(pdf_path)

    # 1b) Recuperacao de arquivo corrompido: reabre via Office em modo de reparo
    # (Word OpenAndRepair / Excel CorruptLoad) antes de cair no LibreOffice.
    if convert_office_via_com(source, pdf_path, log, repair=True):
        log("info", f"PDF criado via Microsoft Office apos recuperacao do arquivo: {pdf_path}")
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
    # Popen (em vez de subprocess.run) para podermos MATAR o soffice se ele travar no
    # timeout. Senao um soffice.exe orfao fica preso ao perfil .lo_profile e trava as
    # conversoes seguintes (notebooks corporativos Windows).
    proc = subprocess.Popen(
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise ManualReviewRequired("Conversao PDF excedeu o tempo limite (LibreOffice encerrado).")
    if proc.returncode != 0:
        raise ManualReviewRequired(f"Falha na conversao PDF: {stderr or stdout}")
    if not pdf_path.exists():
        raise ManualReviewRequired("Conversao executada, mas PDF nao foi encontrado.")
    log("info", f"PDF criado via LibreOffice: {pdf_path}")
    return str(pdf_path)


def convert_to_pdf_in_folder(source_path: str, pdf_dir: str, log: Callable) -> str:
    """Converte o arquivo para a pasta 'PDF' (ao lado dos lotes) mantendo ALI o original E o PDF.

    Para arquivos em error/processing, deixa na pasta PDF tanto UMA copia do arquivo original
    quanto o .pdf convertido (o que e enviado ao workspace). Se a origem ja for PDF, coloca
    apenas UMA copia do PDF (com guarda de colisao) para o lote ficar homogeneo.
    """
    destination = Path(pdf_dir)
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(source_path)
    if not source.exists():
        raise UnsupportedFormat(f"Arquivo nao encontrado para converter: {source_path}")
    if source.suffix.lower() == ".pdf":
        # Ja e PDF: nada a converter; garante UMA copia na pasta PDF (com guarda de colisao).
        target = destination / source.name
        if source.resolve() != target.resolve():
            if target.exists():
                target = destination / f"{source.stem}_{int(time.time())}.pdf"
            shutil.copy2(str(source), str(target))
            log("info", f"PDF colocado na pasta PDF: {target.name}", metadata={"pdf_dir": str(destination)})
        return str(target)
    # Mantem uma copia do arquivo ORIGINAL (error/processing) na pasta PDF, junto com os lotes.
    original_copy = destination / source.name
    if source.resolve() != original_copy.resolve() and not original_copy.exists():
        try:
            shutil.copy2(str(source), str(original_copy))
            log("info", f"Original copiado para a pasta PDF: {original_copy.name}", metadata={"pdf_dir": str(destination)})
        except OSError as exc:
            log("warning", f"Nao foi possivel copiar o original para a pasta PDF: {source.name}: {exc}")
    # Converte a origem para a pasta PDF; o .pdf fica ao lado da copia do original.
    pdf_path = convert_file_to_pdf(str(source), str(destination), log)
    log("info", f"Convertido na pasta PDF: {Path(pdf_path).name}", metadata={"pdf_dir": str(destination)})
    return pdf_path
