from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

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


def wait_monitor_delay(
    timeout_minutes: int,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    task_created_at: Optional[str] = None,
) -> None:
    """Espera o tempo determinado pela automacao SEM abrir o navegador (sem polling continuo).

    O monitoramento e feito uma unica vez, depois desse tempo. Desconta o tempo decorrido na fila.
    """
    from datetime import datetime, timezone
    import math

    total_seconds = max(0, int(timeout_minutes) * 60)
    elapsed_seconds = 0
    if task_created_at:
        try:
            created_str = str(task_created_at)
            if created_str.endswith("Z"):
                created_str = created_str[:-1] + "+00:00"
            created_dt = datetime.fromisoformat(created_str)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            
            now_utc = datetime.now(timezone.utc)
            elapsed_seconds = max(0, int((now_utc - created_dt).total_seconds()))
        except Exception as exc:
            log("warning", f"Nao foi possivel calcular o tempo decorrido na fila: {exc}")

    seconds = max(0, total_seconds - elapsed_seconds)
    if seconds <= 0:
        if elapsed_seconds > 0:
            log("info", f"Tempo de espera decorrido na fila ({elapsed_seconds // 60} min passados). Seguindo para leitura de status.")
        return

    minutes_left = int(math.ceil(seconds / 60))
    log("info", f"Aguardando {minutes_left} min antes do monitoramento unico (sem navegador aberto).")
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
            # Espera de até 6s para a linha do arquivo ficar visível, mitigando flutuações do Ajax
            locator.first.wait_for(state="visible", timeout=6000)
            count = min(locator.count(), 5)
        except Exception:
            count = 0
        for index in range(count):
            row = locator.nth(index)
            try:
                if row.is_visible(timeout=1000):
                    return row
            except Exception:
                continue
    return None


def click_delete_confirm(page) -> bool:
    """Confirma a delecao, dando preferencia a um botao DENTRO de um modal/dialog.

    Restringir ao dialog evita clicar num "Delete"/"OK"/"Confirm" perdido em outro ponto da
    pagina (falso positivo). Se nao houver dialog, tenta a pagina inteira como ultimo recurso.
    """
    scopes: list[Any] = []
    for role in ("dialog", "alertdialog"):
        try:
            candidate = page.get_by_role(role)
            if candidate.count():
                scopes.append(candidate.first)
        except Exception:
            continue
    scopes.append(page)
    for scope in scopes:
        try:
            if click_first(
                [lambda text=text: scope.get_by_role("button", name=text) for text in DELETE_CONFIRM_TEXTS]
                + [lambda text=text: scope.get_by_text(text, exact=True) for text in DELETE_CONFIRM_TEXTS],
                timeout_ms=1500,
            ):
                return True
        except Exception:
            continue
    return False


def actions_cell(row):
    """Ultima celula da linha (coluna Actions), onde fica o icone de deletar."""
    for cell_selector in ("td:last-child", "[role='gridcell']:last-child", "[role='cell']:last-child"):
        try:
            cell = row.locator(cell_selector).last
            if cell.count():
                return cell
        except Exception:
            continue
    return None


def dump_actions_cell_html(row, log: Callable, file_name: str) -> None:
    """Loga o HTML da celula Actions para mapearmos o seletor exato do icone de delete.

    Acionado quando nao achamos/confirmamos o controle: o aria-label/title/classe reais do
    icone ficam no log para deixarmos o clique cirurgico na proxima execucao.
    """
    target = actions_cell(row) or row
    try:
        html = target.evaluate("el => el.outerHTML")
    except Exception:
        return
    if html:
        log(
            "warning",
            f"HTML da area Actions de '{file_name}' (para mapear o icone de delete): {clean_text(html)[:1500]}",
            metadata={"actions_html": html},
        )


def click_row_delete_control(row, log: Callable, file_name: str) -> bool:
    """Clica no controle de deletar DENTRO da linha do arquivo (icone na coluna Actions).

    Ordem: (1) botao cujo aria-label/title casa o NOME do arquivo; (2) botao com 'Delete';
    (3) textos conhecidos de delete; (4) primeiro controle clicavel REAL (button/link) da
    celula Actions. Clicar um <button>/<a> e mais confiavel que clicar um <svg>/<img> solto
    (o icone costuma ser filho de um botao). A delecao so e considerada efetiva apos a
    verificacao por F5 do chamador (a linha precisa sumir), entao um clique impreciso nunca
    apaga e reenvia por engano.
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
            lambda t=text: row.locator(f"button[aria-label*='{t}' i], button[title*='{t}' i]"),
            lambda t=text: row.locator(f"[aria-label*='{t}' i], [title*='{t}' i]"),
        ):
            try:
                control = lookup()
                if control.count() and control.first.is_visible(timeout=400):
                    control.first.click(timeout=4000)
                    return True
            except Exception:
                continue
    cell = actions_cell(row)
    if cell is not None:
        # Preferir controles clicaveis reais; evitar clicar num svg/img solto (pode nao ser o alvo).
        for inner in ("button", "[role='button']", "a[role='button']", "a", "[onclick]"):
            try:
                controls = cell.locator(inner)
                if controls.count() and controls.first.is_visible(timeout=400):
                    controls.first.click(timeout=4000)
                    return True
            except Exception:
                continue
    log("warning", f"Controle de deletar nao encontrado na linha de '{file_name}'.")
    dump_actions_cell_html(row, log, file_name)
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


def locate_row_paginated(page, file_name: str, should_continue: Callable[[], bool] | None = None):
    """A partir da pagina atual, percorre as paginas e retorna a LINHA do arquivo (ou None)."""
    visited = 0
    max_pages = 200
    while visited < max_pages:
        visited += 1
        check_continue(should_continue)
        row = find_file_row(page, file_name)
        if row is not None:
            return row
        if not goto_next_files_page(page):
            return None
    return None


def delete_one_with_verify(
    page,
    target: str,
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
    attempts: int = 2,
) -> bool:
    """Deleta um arquivo e CONFIRMA via F5 que a linha sumiu. So retorna True se sumiu mesmo.

    Sem essa verificacao, um clique impreciso registraria "deletado" e dispararia o reenvio,
    deixando o arquivo duplicado no workspace. Aqui, enquanto a linha existir, nao ha sucesso.
    """
    last_row = None
    # F5 antes da primeira busca: a leitura de status percorre TODAS as paginas e deixa o cursor
    # na ultima; como locate_row_paginated so avanca, sem este reset um alvo numa pagina anterior
    # nao seria encontrado e viraria "deletado" por engano (reenvio -> duplicacao no workspace).
    f5_reopen_files(page, payload, workspace_name, log, should_continue)
    for attempt in range(1, attempts + 1):
        check_continue(should_continue)
        row = locate_row_paginated(page, target, should_continue)
        if row is None:
            log("info", f"'{target}' nao esta na tabela (nada para deletar).")
            return True
        last_row = row
        if not click_row_delete_control(row, log, target):
            return False
        click_delete_confirm(page)  # melhor esforco: algumas UIs deletam sem modal de confirmacao
        f5_reopen_files(page, payload, workspace_name, log, should_continue)
        if locate_row_paginated(page, target, should_continue) is None:
            log("info", f"Delete confirmado (linha sumiu) para: {target}")
            return True
        log("warning", f"'{target}' continua na tabela apos o delete (tentativa {attempt}/{attempts}).")
    # Falhou apos as tentativas: registra o HTML da area Actions para mapearmos o icone correto.
    fresh = locate_row_paginated(page, target, should_continue) or last_row
    if fresh is not None:
        dump_actions_cell_html(fresh, log, target)
    return False


def delete_all_to_fix(
    page,
    names: list[str],
    payload: dict[str, Any],
    workspace_name: str,
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> tuple[list[str], list[str]]:
    """Deleta na web cada arquivo nao-Ready, confirmando via F5 que a linha realmente sumiu."""
    remaining = list(dict.fromkeys(names))
    deleted: list[str] = []
    failed: list[str] = []

    # Sem open_files_tab aqui: delete_one_with_verify faz F5 (que reabre a aba Files na pagina 1)
    # antes de cada busca; abrir a aba aqui seria trabalho redundante.
    for target in remaining:
        check_continue(should_continue)
        if delete_one_with_verify(page, target, payload, workspace_name, log, should_continue=should_continue):
            deleted.append(target)
        else:
            log("warning", f"Delete nao confirmado para: {target} (linha permaneceu na tabela).")
            failed.append(target)

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
    task_created_at = payload.get("task_created_at")

    # 1) Espera o tempo determinado pela automacao, SEM navegador aberto (monitoramento unico).
    wait_monitor_delay(timeout_minutes, log, should_continue=should_continue, task_created_at=task_created_at)

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

        # So reenviamos como PDF o que foi REALMENTE removido da web (delete confirmado por F5)
        # ou que nunca esteve na tabela (NotFound). Delete nao confirmado NAO e reenviado: vira
        # revisao manual, para nunca duplicar o arquivo no workspace (decisao do usuario).
        to_resend = list(dict.fromkeys(deleted + not_found))
        manual_review = list(dict.fromkeys(pending + delete_failed))
        if delete_failed:
            log(
                "warning",
                "Delete nao confirmado: enviados para revisao manual (sem reenvio, para nao duplicar).",
                metadata={"files": delete_failed},
            )
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
