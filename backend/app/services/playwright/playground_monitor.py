from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.services.playwright.browser import click_first, open_persistent_chromium, page_text, safe_error_screenshot, wait_for_text
from app.services.playwright.errors import PlaywrightAutomationError
from app.services.playwright.playground_login import configured_playground_url, ensure_logged_in
from app.services.playwright.playground_workspace import open_workspace
from app.services.playwright.selectors import (
    ERROR_STATUS_TEXTS,
    FILES_TAB_TEXTS,
    PENDING_STATUS_TEXTS,
    PROCESSING_STATUS_TEXTS,
    READY_STATUS_TEXTS,
)


NAME_HEADERS = ["name", "nome"]
STATUS_HEADERS = ["status"]
FILES_TABLE_TEXTS = ["Name", "Status", "Upload date", "Size", "Actions"]
REFRESH_BUTTON_TEXTS = [
    "Refresh",
    "Refresh files",
    "Reload",
    "Atualizar",
    "Atualizar arquivos",
    "Recarregar",
]
FOUND_STATUSES = {"Ready", "Error", "Processing", "Pending"}
FILES_RELOAD_INTERVAL_SECONDS = 30


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


def remember_seen_statuses(last_seen: dict[str, dict[str, str]], statuses: dict[str, dict[str, str]]) -> None:
    for name, status_data in statuses.items():
        if status_data.get("status") in FOUND_STATUSES:
            last_seen[name] = dict(status_data)


def has_regressed_to_not_found(
    statuses: dict[str, dict[str, str]],
    last_seen: dict[str, dict[str, str]],
) -> bool:
    return any(
        status_data.get("status") == "NotFound"
        and last_seen.get(name, {}).get("status") in FOUND_STATUSES
        for name, status_data in statuses.items()
    )


def click_files_refresh_button(page, log: Callable) -> bool:
    clicked = click_first(
        [lambda text=text: page.get_by_role("button", name=text) for text in REFRESH_BUTTON_TEXTS]
        + [lambda text=text: page.get_by_title(text) for text in REFRESH_BUTTON_TEXTS]
        + [lambda text=text: page.locator(f"button[aria-label*='{text}']") for text in REFRESH_BUTTON_TEXTS]
        + [lambda text=text: page.locator(f"[role='button'][aria-label*='{text}']") for text in REFRESH_BUTTON_TEXTS],
        timeout_ms=2500,
    )
    if clicked:
        log("info", "Refresh da aba Files clicado.")
        return True

    try:
        label = page.evaluate(
            """
            () => {
              const words = ['refresh', 'reload', 'atualizar', 'recarregar'];
              const clean = (value) => String(value || '').toLowerCase();
              for (const element of document.querySelectorAll('button, [role="button"]')) {
                const text = [
                  element.innerText,
                  element.textContent,
                  element.getAttribute('aria-label'),
                  element.getAttribute('title'),
                ].map(clean).join(' ');
                if (words.some((word) => text.includes(word))) {
                  element.click();
                  return text.trim() || 'refresh';
                }
              }
              return '';
            }
            """
        )
        if label:
            log("info", "Refresh da aba Files clicado.", metadata={"button": label})
            return True
    except Exception:
        pass
    return False


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


def refresh_files_view(
    page,
    workspace_name: str,
    expected_names: list[str],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> bool:
    check_continue(should_continue)
    clicked = click_files_refresh_button(page, log)
    if clicked:
        statuses = wait_for_expected_rows(page, expected_names, timeout_seconds=12, should_continue=should_continue)
        if statuses_have_expected_rows(statuses):
            return True
        log("warning", "Refresh da aba Files nao repos linhas esperadas; reabrindo aba Files.")

    try:
        check_continue(should_continue)
        open_files_tab(page, log)
        statuses = wait_for_expected_rows(page, expected_names, timeout_seconds=8, should_continue=should_continue)
        if statuses_have_expected_rows(statuses):
            return True
    except Exception as exc:
        log("warning", f"Nao foi possivel reabrir somente a aba Files: {exc}")

    try:
        check_continue(should_continue)
        log("warning", "Reabrindo Workspace para recuperar tabela Files.")
        open_workspace(page, workspace_name, log, expected_area="files")
        open_files_tab(page, log)
        statuses = wait_for_expected_rows(page, expected_names, timeout_seconds=12, should_continue=should_continue)
        return statuses_have_expected_rows(statuses)
    except Exception as exc:
        log("warning", f"Falha ao recuperar Workspace/Files antes da proxima leitura: {exc}")
        return False


def reload_files_view(
    page,
    workspace_name: str,
    expected_names: list[str],
    payload: dict[str, Any],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> bool:
    try:
        check_continue(should_continue)
        log("info", "Recarregando aba Files para atualizar status.")
        page.reload(wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        check_continue(should_continue)
        ensure_logged_in(page, payload, log)
        check_continue(should_continue)
        open_workspace(page, workspace_name, log, expected_area="files")
        check_continue(should_continue)
        open_files_tab(page, log)
        statuses = wait_for_expected_rows(page, expected_names, timeout_seconds=12, should_continue=should_continue)
        if statuses_have_expected_rows(statuses):
            log("info", "Aba Files recarregada com linhas esperadas.")
            return True
        log("warning", "Reload da aba Files nao repos linhas esperadas; tentando refresh/reabertura.")
    except Exception as exc:
        log("warning", f"Falha ao recarregar aba Files; tentando recuperacao: {exc}")
    return refresh_files_view(page, workspace_name, expected_names, log, should_continue=should_continue)


def read_statuses_with_recovery(
    page,
    workspace_name: str,
    expected_names: list[str],
    last_seen: dict[str, dict[str, str]],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, dict[str, str]]:
    statuses = read_file_statuses(page, expected_names)
    if not has_regressed_to_not_found(statuses, last_seen):
        return statuses

    missing = [
        name for name, status_data in statuses.items()
        if status_data.get("status") == "NotFound" and name in last_seen
    ]
    log(
        "warning",
        "Leitura retornou NotFound para arquivos ja vistos; recuperando aba Files antes de registrar.",
        metadata={"files": missing, "last_seen": {name: last_seen.get(name) for name in missing}},
    )
    refresh_files_view(page, workspace_name, expected_names, log, should_continue=should_continue)
    return read_file_statuses(page, expected_names)


def wait_for_monitor_reload(
    deadline: float,
    should_continue: Callable[[], bool] | None = None,
    interval_seconds: int = FILES_RELOAD_INTERVAL_SECONDS,
) -> bool:
    sleep_deadline = min(deadline, time.monotonic() + max(1, interval_seconds))
    while time.monotonic() < sleep_deadline:
        check_continue(should_continue)
        time.sleep(min(1, max(0, sleep_deadline - time.monotonic())))
    return time.monotonic() < deadline


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
    reload_interval_seconds = int(payload.get("monitor_reload_interval_seconds") or FILES_RELOAD_INTERVAL_SECONDS)
    deadline = time.monotonic() + (timeout_minutes * 60)
    final_statuses: dict[str, dict[str, str]] = {}
    last_seen_statuses: dict[str, dict[str, str]] = {}

    browser = None
    try:
        check_continue(should_continue)
        browser = open_persistent_chromium(
            user_id,
            headless=payload.get("headless"),
            browser_channel=payload.get("browser_channel"),
        )
        page = browser.page
        log("info", "Chromium iniciado.")
        check_continue(should_continue)
        page.goto(configured_playground_url(payload), wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        ensure_logged_in(page, payload, log)
        check_continue(should_continue)
        open_workspace(page, workspace_name, log, expected_area="files")
        check_continue(should_continue)
        open_files_tab(page, log)

        while time.monotonic() < deadline:
            check_continue(should_continue)
            final_statuses = read_statuses_with_recovery(
                page,
                workspace_name,
                expected_names,
                last_seen_statuses,
                log,
                should_continue=should_continue,
            )
            remember_seen_statuses(last_seen_statuses, final_statuses)
            all_ready = True
            for name, status_data in final_statuses.items():
                status = status_data["status"]
                log("info", f"Status lido: {name} = {status}", file_id=_file_id_for_name(files, name), metadata=status_data)
                if status == "Ready":
                    continue
                all_ready = False
                if status == "Error":
                    break
            if all_ready:
                return {
                    "status": "completed",
                    "ready": list(expected_names),
                    "retry": [],
                    "manual_review": [],
                    "statuses": final_statuses,
                }
            if not wait_for_monitor_reload(deadline, should_continue=should_continue, interval_seconds=reload_interval_seconds):
                break
            reload_files_view(page, workspace_name, expected_names, payload, log, should_continue=should_continue)

        retry: list[str] = []
        manual_review: list[str] = []
        for name, status_data in final_statuses.items():
            status = status_data["status"]
            if status in {"Error", "Pending", "NotFound"}:
                retry.append(name)
            elif status == "Processing":
                manual_review.append(name)
        if retry:
            log("warning", "Timeout de monitoramento com arquivos para conversao/retry.", metadata={"files": retry})
        if manual_review:
            log("warning", "Processing constante exige revisao manual.", metadata={"files": manual_review})
        return {
            "status": "manual_review" if manual_review and not retry else "completed",
            "ready": [name for name, data in final_statuses.items() if data["status"] == "Ready"],
            "retry": retry,
            "manual_review": manual_review,
            "statuses": final_statuses,
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
