from __future__ import annotations

import time
from typing import Any, Callable

from app.core.config import settings
from app.services.playwright.browser import click_first, fill_first, open_persistent_chromium, page_text, safe_error_screenshot
from app.services.playwright.errors import ManualReviewRequired, PlaywrightAutomationError, UserNotFound
from app.services.playwright.playground_login import configured_playground_url, ensure_logged_in
from app.services.playwright.playground_workspace import open_workspace
from app.services.playwright.selectors import ADD_USER_TEXTS, ROLE_TEXTS, USER_IDENTIFIER_FIELDS, USER_MANAGEMENT_TEXTS


def click_user_management(page, log: Callable) -> None:
    clicked = click_first(
        [lambda text=text: page.get_by_role("tab", name=text) for text in USER_MANAGEMENT_TEXTS]
        + [lambda text=text: page.get_by_role("button", name=text) for text in USER_MANAGEMENT_TEXTS]
        + [lambda text=text: page.get_by_text(text, exact=False) for text in USER_MANAGEMENT_TEXTS],
        timeout_ms=5000,
    )
    if not clicked:
        raise PlaywrightAutomationError("User Management nao encontrado.")
    log("info", "User Management aberto.")


def click_add_user(page, log: Callable) -> None:
    clicked = click_first(
        [lambda text=text: page.get_by_role("button", name=text) for text in ADD_USER_TEXTS]
        + [lambda text=text: page.get_by_text(text, exact=False) for text in ADD_USER_TEXTS],
        timeout_ms=5000,
    )
    if not clicked:
        raise PlaywrightAutomationError("Add User nao encontrado.")
    log("info", "Add User aberto.")


def fill_user_identifier(page, identifier: str, log: Callable) -> None:
    filled = fill_first(
        [lambda label=label: page.get_by_label(label) for label in USER_IDENTIFIER_FIELDS]
        + [lambda label=label: page.get_by_placeholder(label) for label in USER_IDENTIFIER_FIELDS]
        + [lambda: page.locator('input[type="text"]')],
        identifier,
        timeout_ms=4000,
    )
    if not filled:
        raise UserNotFound("Campo de usuario nao encontrado.")
    log("info", "Usuario informado.")
    time.sleep(1)
    clicked = click_first(
        [
            lambda: page.get_by_text(identifier, exact=True),
            lambda: page.get_by_text(identifier, exact=False),
        ],
        timeout_ms=4000,
    )
    if clicked:
        log("info", "Usuario selecionado na sugestao.")


def select_role(page, role: str, log: Callable) -> None:
    normalized = (role or "Reader").strip().lower()
    labels = ROLE_TEXTS.get(normalized, ROLE_TEXTS["reader"])
    clicked = click_first(
        [lambda text=text: page.get_by_role("radio", name=text) for text in labels]
        + [lambda text=text: page.get_by_role("option", name=text) for text in labels]
        + [lambda text=text: page.get_by_text(text, exact=False) for text in labels],
        timeout_ms=4000,
    )
    if not clicked:
        raise ManualReviewRequired(f"Role nao encontrado para selecao automatica: {role}")
    log("info", f"Role selecionado: {role}")


def click_final_add(page, log: Callable) -> None:
    clicked = click_first(
        [lambda text=text: page.get_by_role("button", name=text) for text in ["Add", "Adicionar"]]
        + [lambda text=text: page.get_by_text(text, exact=True) for text in ["Add", "Adicionar"]],
        timeout_ms=5000,
    )
    if not clicked:
        raise PlaywrightAutomationError("Botao Add final nao encontrado.")
    log("info", "Add concluido.")


def add_playground_user_to_workspace(
    task_id: int,
    user_id: int | None,
    payload: dict[str, Any],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    workspace_name = str(payload.get("workspace_name") or "").strip()
    identifier = str(
        payload.get("user_identifier")
        or payload.get("network_id")
        or payload.get("external_user_id")
        or payload.get("external_user_email")
        or ""
    ).strip()
    role = str(payload.get("role") or "Reader").strip()
    if not workspace_name:
        raise PlaywrightAutomationError("Payload sem workspace_name.")
    if not identifier:
        raise UserNotFound("Payload sem user_identifier/network_id.")

    browser = None
    try:
        browser = open_persistent_chromium(
            user_id,
            headless=payload.get("headless"),
            browser_channel=payload.get("browser_channel"),
        )
        page = browser.page
        log("info", "Chromium iniciado.")
        page.goto(configured_playground_url(payload), wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        ensure_logged_in(page, payload, log, should_continue)
        open_workspace(page, workspace_name, log, expected_area="users")
        click_user_management(page, log)
        if identifier.lower() in page_text(page).lower() and role.lower() in page_text(page).lower():
            log("warning", "Usuario ja consta no Workspace com role aparente.")
            return {"already_exists": True, "role": role, "user_identifier": identifier}
        click_add_user(page, log)
        fill_user_identifier(page, identifier, log)
        select_role(page, role, log)
        click_final_add(page, log)
        body = page_text(page).lower()
        if "not found" in body or "nao encontrado" in body or "não encontrado" in body:
            raise UserNotFound(f"Usuario nao encontrado: {identifier}")
        if identifier.lower() not in body:
            log("warning", "Usuario nao apareceu imediatamente na lista; validar manualmente se necessario.")
        log("info", "Usuario adicionado ao Workspace.")
        return {"user_identifier": identifier, "role": role, "workspace_name": workspace_name}
    except Exception:
        if browser and browser.page:
            safe_error_screenshot(browser.page, task_id, log)
        raise
    finally:
        if browser:
            browser.close()
            log("info", "Navegador fechado.")
