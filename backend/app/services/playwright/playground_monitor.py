from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.services.playwright.browser import click_first, open_persistent_chromium, page_text, safe_error_screenshot, wait_for_text
from app.services.playwright.errors import PlaywrightAutomationError
from app.services.playwright.playground_login import configured_playground_url, ensure_logged_in
from app.services.playwright.playground_workspace import open_workspace, wait_for_workspace_area
from app.services.playwright.selectors import (
    DELETE_CONFIRM_TEXTS,
    DELETE_FILE_CONTROL_TEXTS,
    ERROR_STATUS_TEXTS,
    FILES_TAB_TEXTS,
    NEXT_PAGE_TEXTS,
    PENDING_STATUS_TEXTS,
    PROCESSING_STATUS_TEXTS,
    READY_STATUS_TEXTS,
)


NAME_HEADERS = ["name", "nome"]
STATUS_HEADERS = ["status"]
FILES_TABLE_TEXTS = ["Name", "Status", "Upload date", "Size", "Actions"]
FOUND_STATUSES = {"Ready", "Error", "Processing", "Pending"}


def check_continue(should_continue: Callable[[], bool] | None) -> None:
    if should_continue:
        should_continue()


def clean_text(value: str) -> str:
    return " ".join(str(value or "").split())


def normalize_status(text: str) -> str:
    lower = (text or "").lower()
    if any(value.lower() in lower for value in READY_STATUS_TEXTS):
        return "Ready"
    if any(value.lower() in lower for value in ERROR_STATUS_TEXTS):
        return "Error"
    if any(value.lower() in lower for value in PROCESSING_STATUS_TEXTS):
        return "Processing"
    if any(value.lower() in lower for value in PENDING_STATUS_TEXTS):
        return "Pending"
    return "Unknown"


def open_files_tab(page, log: Callable) -> None:
    clicked = click_first(
        [lambda text=text: page.get_by_role("tab", name=text) for text in FILES_TAB_TEXTS]
        + [lambda text=text: page.get_by_role("button", name=text) for text in FILES_TAB_TEXTS]
        + [lambda text=text: page.get_by_text(text, exact=True) for text in FILES_TAB_TEXTS],
        timeout_ms=5000,
    )
    if clicked:
        log("info", "Aba Files aberta.")
    elif "files" in page_text(page).lower() or "arquivos" in page_text(page).lower():
        log("info", "Aba Files ja estava visivel.")
    else:
        raise PlaywrightAutomationError("Aba Files nao encontrada.")
    wait_for_text(page, FILES_TABLE_TEXTS, timeout_ms=10000)


def expected_file_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("file_name") or item.get("name") or Path(str(item.get("path") or item.get("temp_path") or "")).name)
    return Path(str(item)).name


def read_structured_file_rows(page) -> list[dict[str, Any]]:
    try:
        rows = page.evaluate(
            """
            () => {
              const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
              const textOf = (element) => {
                if (!element) return '';
                const parts = [
                  element.innerText || element.textContent || '',
                  element.getAttribute('aria-label') || '',
                  element.getAttribute('title') || '',
                ];
                element.querySelectorAll('[aria-label], [title]').forEach((child) => {
                  parts.push(child.getAttribute('aria-label') || '');
                  parts.push(child.getAttribute('title') || '');
                });
                return clean(parts.filter(Boolean).join(' '));
              };
              const result = [];
              document.querySelectorAll('table').forEach((table) => {
                const headers = Array.from(table.querySelectorAll('thead th, thead [role="columnheader"], tr:first-child th'))
                  .map(textOf)
                  .filter(Boolean);
                table.querySelectorAll('tbody tr').forEach((row) => {
                  const cells = Array.from(row.querySelectorAll('td, th, [role="cell"], [role="gridcell"]'))
                    .map(textOf)
                    .filter(Boolean);
                  const text = textOf(row);
                  if (cells.length || text) result.push({ source: 'table', headers, cells, text });
                });
              });
              document.querySelectorAll('[role="row"]').forEach((row) => {
                if (row.closest('table')) return;
                const cells = Array.from(row.querySelectorAll('[role="cell"], [role="gridcell"], td, th'))
                  .map(textOf)
                  .filter(Boolean);
                const text = textOf(row);
                if (cells.length || text) result.push({ source: 'role-row', headers: [], cells, text });
              });
              return result;
            }
            """
        )
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def header_index(headers: list[str], aliases: list[str]) -> int | None:
    normalized = [clean_text(header).lower() for header in headers]
    for index, header in enumerate(normalized):
        if any(alias in header for alias in aliases):
            return index
    return None


def status_text_from_row(row: dict[str, Any], expected_name: str) -> str:
    cells = [clean_text(cell) for cell in row.get("cells") or [] if clean_text(cell)]
    headers = [clean_text(header) for header in row.get("headers") or [] if clean_text(header)]
    status_index = header_index(headers, STATUS_HEADERS)
    if status_index is not None and status_index < len(cells):
        return cells[status_index]

    name_index = header_index(headers, NAME_HEADERS)
    for index, cell in enumerate(cells):
        if name_index is not None and index == name_index:
            continue
        if expected_name.lower() in cell.lower():
            continue
        if normalize_status(cell) != "Unknown":
            return cell
    return clean_text(row.get("text") or "")


def read_file_statuses(page, expected_names: list[str]) -> dict[str, dict[str, str]]:
    statuses: dict[str, dict[str, str]] = {}
    structured_rows = read_structured_file_rows(page)
    row_selectors = ["table tbody tr", "[role='row']"]
    row_texts: list[str] = []
    for selector in row_selectors:
        try:
            rows = page.locator(selector)
            count = min(rows.count(), 300)
            for index in range(count):
                text = rows.nth(index).inner_text(timeout=1000)
                if text:
                    row_texts.append(text)
        except Exception:
            continue
    if not row_texts:
        row_texts = [page_text(page)]

    for name in expected_names:
        match_text = ""
        status_text = ""
        for row in structured_rows:
            row_text = clean_text(row.get("text") or " ".join(row.get("cells") or []))
            if name.lower() in row_text.lower():
                match_text = row_text
                status_text = status_text_from_row(row, name)
                break
        if not match_text:
            for row_text in row_texts:
                if name.lower() in row_text.lower():
                    match_text = clean_text(row_text)
                    status_text = match_text
                    break
        if match_text:
            statuses[name] = {
                "status": normalize_status(status_text or match_text),
                "raw": match_text,
                "status_text": status_text or match_text,
            }
        else:
            statuses[name] = {"status": "NotFound", "raw": "", "status_text": ""}
    return statuses


def statuses_have_expected_rows(statuses: dict[str, dict[str, str]]) -> bool:
    return any(data.get("status") in FOUND_STATUSES for data in statuses.values())


def wait_for_expected_rows(
    page,
    expected_names: list[str],
    timeout_seconds: int,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + max(1, timeout_seconds)
    statuses: dict[str, dict[str, str]] = {}
    while time.monotonic() < deadline:
        check_continue(should_continue)
        statuses = read_file_statuses(page, expected_names)
        if statuses_have_expected_rows(statuses):
            return statuses
        time.sleep(1)
    return statuses or read_file_statuses(page, expected_names)


def wait_monitor_delay(timeout_minutes: int, log: Callable, should_continue: Callable[[], bool] | None = None) -> None:
    """Espera o tempo determinado pela automacao SEM abrir o navegador (sem polling continuo).

    O monitoramento e feito uma unica vez, depois desse tempo.
    """
    seconds = max(0, int(timeout_minutes) * 60)
    if seconds <= 0:
        return
    log("info", f"Aguardando {timeout_minutes} min antes do monitoramento unico (sem navegador aberto).")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        check_continue(should_continue)
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    log("info", "Tempo de espera concluido; abrindo o Chromium para o monitoramento.")


def open_workspace_for_monitor(page, payload: dict[str, Any], workspace_name: str, log: Callable) -> None:
    """Abre o workspace direto pela Playground URL salva; cai para busca por nome se faltar."""
    direct_url = str(payload.get("workspace_playground_url") or "").strip()
    if direct_url:
        page.goto(direct_url, wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        ensure_logged_in(page, payload, log)
        if wait_for_workspace_area(page, "files", timeout_ms=settings.WORKSPACE_AREA_TIMEOUT_MS):
            log("info", "Workspace aberto direto pela Playground URL (monitoramento).", metadata={"workspace_playground_url": direct_url})
            return
        log("warning", "Playground URL direta nao carregou a area de arquivos; caindo para busca por nome.")
    else:
        page.goto(configured_playground_url(payload), wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        ensure_logged_in(page, payload, log)
    open_workspace(page, workspace_name, log, expected_area="files")


def page_rows_signature(page) -> str:
    parts: list[str] = []
    try:
        rows = page.locator("table tbody tr")
        count = min(rows.count(), 60)
        for index in range(count):
            try:
                parts.append(clean_text(rows.nth(index).inner_text(timeout=500)))
            except Exception:
                continue
    except Exception:
        pass
    if not parts:
        return clean_text(page_text(page))[:2000]
    return "||".join(parts)


def goto_next_files_page(page) -> bool:
    """Clica em ">" (proxima pagina). Retorna True se a tabela mudou (havia outra pagina)."""
    signature_before = page_rows_signature(page)
    clicked = click_first(
        [lambda text=text: page.get_by_role("button", name=text, exact=True) for text in NEXT_PAGE_TEXTS]
        + [lambda text=text: page.get_by_role("link", name=text, exact=True) for text in NEXT_PAGE_TEXTS]
        + [lambda text=text: page.locator(f"[aria-label*='{text}' i]") for text in NEXT_PAGE_TEXTS]
        + [lambda text=text: page.locator(f"[title*='{text}' i]") for text in NEXT_PAGE_TEXTS],
        timeout_ms=1500,
    )
    if not clicked:
        return False
    for _ in range(12):
        time.sleep(0.3)
        if page_rows_signature(page) != signature_before:
            return True
    return False


def best_status(current: dict[str, str], candidate: dict[str, str]) -> dict[str, str]:
    order = {"Ready": 4, "Error": 3, "Processing": 2, "Pending": 1}
    cur = current.get("status")
    cand = candidate.get("status")
    if cand == "Ready":
        return candidate
    if cur not in FOUND_STATUSES and cand in FOUND_STATUSES:
        return candidate
    if order.get(cand, 0) > order.get(cur, 0):
        return candidate
    return current


def read_all_pages_statuses(
    page,
    expected_names: list[str],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, dict[str, str]]:
    """Le o status de cada arquivo percorrendo TODAS as paginas (clicando em ">")."""
    merged: dict[str, dict[str, str]] = {
        name: {"status": "NotFound", "raw": "", "status_text": ""} for name in expected_names
    }
    page_index = 0
    max_pages = 200
    while page_index < max_pages:
        check_continue(should_continue)
        page_index += 1
        statuses = wait_for_expected_rows(page, expected_names, timeout_seconds=8, should_continue=should_continue)
        found_here: list[str] = []
        for name, data in statuses.items():
            if data.get("status") in FOUND_STATUSES:
                merged[name] = best_status(merged[name], data)
                found_here.append(name)
        log("info", f"Pagina {page_index} de Status lida.", metadata={"found": found_here})
        if all(merged[name]["status"] == "Ready" for name in expected_names):
            break
        if not goto_next_files_page(page):
            break
    return merged


def find_file_row(page, file_name: str):
    candidates = [
        page.locator("table tbody tr").filter(has_text=file_name),
        page.locator("[role='row']").filter(has_text=file_name),
    ]
    for locator in candidates:
        try:
            count = min(locator.count(), 5)
        except Exception:
            count = 0
        for index in range(count):
            row = locator.nth(index)
            try:
                if row.is_visible(timeout=500):
                    return row
            except Exception:
                continue
    return None


def click_delete_confirm(page) -> bool:
    try:
        return click_first(
            [lambda text=text: page.get_by_role("button", name=text) for text in DELETE_CONFIRM_TEXTS]
            + [lambda text=text: page.get_by_text(text, exact=True) for text in DELETE_CONFIRM_TEXTS],
            timeout_ms=2000,
        )
    except Exception:
        return False


def click_row_delete_control(row, log: Callable, file_name: str) -> bool:
    """Clica no controle de deletar DENTRO da linha do arquivo (icone folha+x na coluna Actions).

    Tenta primeiro por aria-label/title/texto; se nao houver, clica no unico controle clicavel
    da ultima celula (Actions). A delecao so e considerada efetiva apos a confirmacao por F5
    feita pelo chamador (a linha precisa sumir), entao um clique impreciso nunca apaga e reenvia.
    """
    # Caminho preciso (AWS Cloudscape): o botao de deletar tem aria-label/title = 'Delete "<arquivo>"'.
    # Casar pelo NOME do arquivo no aria-label e cirurgico; combinado ao escopo de linha, e exato.
    for lookup in (
        lambda: row.get_by_role("button", name=re.compile(re.escape(file_name))),
        lambda: row.get_by_role("button", name=re.compile(r"Delete", re.IGNORECASE)),
        lambda: row.locator("button[aria-label*='Delete' i], button[title*='Delete' i]"),
    ):
        try:
            control = lookup()
            if control.count() and control.first.is_visible(timeout=400):
                control.first.click(timeout=4000)
                return True
        except Exception:
            continue
    for text in DELETE_FILE_CONTROL_TEXTS:
        for lookup in (
            lambda t=text: row.get_by_role("button", name=t),
            lambda t=text: row.locator(f"[aria-label*='{t}' i]"),
            lambda t=text: row.locator(f"[title*='{t}' i]"),
        ):
            try:
                control = lookup()
                if control.count() and control.first.is_visible(timeout=400):
                    control.first.click(timeout=4000)
                    return True
            except Exception:
                continue
    for cell_selector in ("td:last-child", "[role='gridcell']:last-child", "[role='cell']:last-child"):
        try:
            cell = row.locator(cell_selector).last
            controls = cell.locator("button, [role='button'], a, svg, img")
            count = controls.count()
        except Exception:
            count = 0
            controls = None
        if controls is not None and count >= 1:
            try:
                controls.first.click(timeout=4000)
                return True
            except Exception:
                continue
    log("warning", f"Controle de deletar nao encontrado na linha de '{file_name}'.")
    return False


def f5_reopen_files(page, payload: dict[str, Any], workspace_name: str, log: Callable, should_continue: Callable[[], bool] | None = None) -> None:
    """Recarrega com F5 e reabre a aba Files (a delecao pode demorar para refletir)."""
    check_continue(should_continue)
    try:
        page.reload(wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
    except Exception as exc:
        log("warning", f"Falha no F5 da aba Files: {exc}")
    ensure_logged_in(page, payload, log)
    try:
        if not wait_for_workspace_area(page, "files", timeout_ms=8000):
            open_workspace_for_monitor(page, payload, workspace_name, log)
    except Exception:
        open_workspace_for_monitor(page, payload, workspace_name, log)
    try:
        open_files_tab(page, log)
    except Exception as exc:
        log("warning", f"Nao foi possivel reabrir a aba Files apos o F5: {exc}")


def find_first_present_paginated(page, names: list[str], should_continue: Callable[[], bool] | None = None) -> str | None:
    """A partir da pagina atual (1), percorre as paginas e retorna o primeiro nome presente."""
    visited = 0
    max_pages = 200
    while visited < max_pages:
        visited += 1
        check_continue(should_continue)
        for name in names:
            if find_file_row(page, name) is not None:
                return name
        if not goto_next_files_page(page):
            return None
    return None


def delete_all_to_fix(
    page,
    names: list[str],
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> tuple[list[str], list[str]]:
    """Deleta na web cada arquivo nao-Ready, confirmando por F5 (a linha precisa sumir).

    Retorna (deletados_confirmados, falhas). Falhas NAO sao reenviadas (viram revisao manual),
    para nunca duplicar arquivos no workspace.
    """
    remaining = list(dict.fromkeys(names))
    deleted: list[str] = []
    failed: list[str] = []
    safety = 0
    max_iter = len(remaining) * 3 + 5
    while remaining and safety < max_iter:
        safety += 1
        # Comeca cada passada na primeira pagina (estado limpo).
        f5_reopen_files(page, payload, workspace_name, log, should_continue=should_continue)
        target = find_first_present_paginated(page, remaining, should_continue=should_continue)
        if target is None:
            failed.extend(remaining)
            remaining.clear()
            break
        row = find_file_row(page, target)
        clicked = click_row_delete_control(row, log, target) if row is not None else False
        if clicked:
            click_delete_confirm(page)
            log("info", f"Delete acionado na web para: {target}; recarregando com F5.")
        # F5 apos cada clique (a delecao pode demorar).
        f5_reopen_files(page, payload, workspace_name, log, should_continue=should_continue)
        if clicked and find_first_present_paginated(page, [target], should_continue=should_continue) is None:
            deleted.append(target)
            log("info", f"Delecao confirmada (a linha sumiu): {target}")
        else:
            failed.append(target)
            log("warning", f"Delecao NAO confirmada para '{target}'; marcado para revisao manual (nao sera reenviado).")
        if target in remaining:
            remaining.remove(target)
    if remaining:
        failed.extend(remaining)
    return deleted, failed


def monitor_workspace_files_status(
    task_id: int,
    user_id: int | None,
    payload: dict[str, Any],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    workspace_name = str(payload.get("workspace_name") or "").strip()
    if not workspace_name:
        raise PlaywrightAutomationError("Payload sem workspace_name.")
    files = payload.get("files") or []
    expected_names = [name for name in [expected_file_name(item) for item in files] if name]
    if not expected_names:
        raise PlaywrightAutomationError("Payload sem arquivos para monitorar.")

    timeout_minutes = int(payload.get("monitoring_timeout_minutes") or settings.DEFAULT_MONITORING_TIMEOUT_MINUTES)

    # 1) Espera o tempo determinado pela automacao, SEM navegador aberto (monitoramento unico).
    wait_monitor_delay(timeout_minutes, log, should_continue=should_continue)

    browser = None
    try:
        check_continue(should_continue)
        browser = open_persistent_chromium(
            user_id,
            headless=payload.get("headless"),
            browser_channel=payload.get("browser_channel"),
        )
        page = browser.page
        log("info", "Chromium iniciado (monitoramento unico apos o tempo determinado).")
        check_continue(should_continue)
        open_workspace_for_monitor(page, payload, workspace_name, log)
        check_continue(should_continue)
        open_files_tab(page, log)

        # 2) Leitura unica de status, percorrendo todas as paginas (">" ate nao carregar mais).
        statuses = read_all_pages_statuses(page, expected_names, log, should_continue=should_continue)
        for name in expected_names:
            log(
                "info",
                f"Status lido: {name} = {statuses.get(name, {}).get('status')}",
                file_id=_file_id_for_name(files, name),
                metadata=statuses.get(name),
            )

        ready = [name for name in expected_names if statuses.get(name, {}).get("status") == "Ready"]
        # Pending = acao manual (nao tratar automaticamente).
        pending = [name for name in expected_names if statuses.get(name, {}).get("status") == "Pending"]
        # Todo nao-Ready que nao for Pending entra no tratamento (Error/Processing/NotFound/Unknown).
        to_fix = [name for name in expected_names if name not in ready and name not in pending]
        not_found = [name for name in to_fix if statuses.get(name, {}).get("status") == "NotFound"]
        deletable = [name for name in to_fix if name not in not_found]

        if ready:
            log("info", "Arquivos prontos (Ready).", metadata={"files": ready})
        if pending:
            log("warning", "Arquivos em Pending: tratados como acao manual.", metadata={"files": pending})
        if to_fix:
            log("warning", "Arquivos nao-Ready: deletar na web + converter PDF + reenviar.", metadata={"files": to_fix})

        # 3) Deleta na web (com confirmacao por F5) os que estao na tabela.
        deleted, delete_failed = delete_all_to_fix(
            page, deletable, payload, workspace_name, log, should_continue=should_continue
        )

        # NotFound nao estao na tabela (nada a deletar) -> serao reenviados mesmo assim.
        to_resend = deleted + not_found
        manual_review = pending + delete_failed
        return {
            "status": "completed",
            "ready": ready,
            "manual_review": manual_review,
            "to_resend": to_resend,
            "deleted": deleted,
            "delete_failed": delete_failed,
            "not_found": not_found,
            "statuses": statuses,
        }
    except Exception:
        if browser and browser.page:
            safe_error_screenshot(browser.page, task_id, log)
        raise
    finally:
        if browser:
            browser.close()
            log("info", "Navegador fechado.")


def _file_id_for_name(files: list[Any], name: str) -> int | None:
    for item in files:
        if isinstance(item, dict) and expected_file_name(item) == name:
            value = item.get("file_id") or item.get("id")
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None
    return None
