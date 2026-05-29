from __future__ import annotations

import re
import time
from typing import Any, Callable
from urllib.parse import urljoin

from app.core.config import settings
from app.services.playwright.browser import (
    click_first,
    fill_first,
    open_persistent_chromium,
    page_text,
    safe_error_screenshot,
    wait_for_text,
)
from app.services.playwright.errors import PlaywrightAutomationError, WorkspaceNotFound
from app.services.playwright.playground_login import configured_playground_url, ensure_logged_in
from app.services.playwright.selectors import (
    ALL_WORKSPACE_TEXTS,
    CHOOSE_FILES_TEXTS,
    CREATE_WORKSPACE_TEXTS,
    DATA_LANGUAGE_FIELDS,
    EMBEDDING_MODEL_FIELDS,
    FILES_TAB_TEXTS,
    UPLOAD_AREA_TEXTS,
    UPLOAD_FILES_TEXTS,
    USER_MANAGEMENT_TEXTS,
    WORKSPACE_DESCRIPTION_FIELDS,
    WORKSPACE_FILTER_FIELDS,
    WORKSPACE_NAME_FIELDS,
)

DEFAULT_PLAYGROUND_DATA_LANGUAGE = "English"
WORKSPACE_EXPECTED_AREAS = {
    "upload": UPLOAD_AREA_TEXTS,
    "files": FILES_TAB_TEXTS,
    "users": USER_MANAGEMENT_TEXTS,
}
WORKSPACE_AREA_LOGS = {
    "upload": "Workspace carregado com area de upload.",
    "files": "Workspace carregado com area de arquivos.",
    "users": "Workspace carregado com area de usuarios.",
}


def normalize_data_languages(languages: list[str] | None) -> list[str]:
    normalized = []
    for item in languages or []:
        language = str(item).strip()
        if language and language not in normalized:
            normalized.append(language)
    return normalized


def is_default_playground_language(language: str) -> bool:
    return language.strip().lower() == DEFAULT_PLAYGROUND_DATA_LANGUAGE.lower()


def _field_locators(page, labels: list[str]):
    return (
        [lambda label=label: page.get_by_label(label) for label in labels]
        + [lambda label=label: page.get_by_placeholder(label) for label in labels]
        + [lambda label=label: page.get_by_role("textbox", name=label) for label in labels]
    )


def fill_field(page, labels: list[str], value: str, required: bool = True) -> bool:
    if value is None or str(value).strip() == "":
        return not required
    filled = fill_first(_field_locators(page, labels), str(value), timeout_ms=3000)
    if not filled and required:
        raise PlaywrightAutomationError(f"Campo nao encontrado: {', '.join(labels)}")
    return filled


def select_option(page, labels: list[str], value: str, required: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return not required
    value = str(value).strip()
    for label in labels:
        try:
            page.get_by_label(label).select_option(label=value, timeout=2500)
            return True
        except Exception:
            pass
        try:
            page.get_by_label(label).select_option(value=value, timeout=2500)
            return True
        except Exception:
            pass
    clicked = click_first(
        [lambda label=label: page.get_by_label(label) for label in labels]
        + [lambda label=label: page.get_by_text(label, exact=False) for label in labels],
        timeout_ms=2500,
    )
    if clicked:
        try:
            page.get_by_text(value, exact=False).first.click(timeout=3000)
            return True
        except Exception:
            pass
    if required:
        raise PlaywrightAutomationError(f"Opcao nao encontrada: {value}")
    return False


def _count(locator) -> int:
    try:
        return locator.count()
    except Exception:
        return 0


def _visible(locator, timeout_ms: int = 1000) -> bool:
    try:
        return _count(locator) > 0 and locator.first.is_visible(timeout=timeout_ms)
    except Exception:
        return False


def _click_visible(locators: list, timeout_ms: int = 2500) -> bool:
    for locator in locators:
        try:
            if _visible(locator, timeout_ms=timeout_ms):
                locator.first.click(timeout=timeout_ms)
                return True
        except Exception:
            continue
    return False


def open_data_languages_selector(page) -> bool:
    locators = []
    for label in DATA_LANGUAGE_FIELDS:
        locators.extend(
            [
                page.get_by_role("combobox", name=label),
                page.get_by_label(label),
                page.get_by_text(label, exact=False),
            ]
        )
    locators.extend(
        [
            page.locator("[aria-label*='Data'][aria-label*='Language']"),
            page.locator("[aria-labelledby*='data'][aria-labelledby*='language']"),
        ]
    )
    return _click_visible(locators, timeout_ms=3000)


def fill_data_language_search(page, language: str) -> bool:
    search_labels = DATA_LANGUAGE_FIELDS + [
        "Search",
        "Search language",
        "Search languages",
        "Buscar",
        "Pesquisar",
    ]
    locators = []
    for label in search_labels:
        locators.extend(
            [
                page.get_by_role("combobox", name=label),
                page.get_by_role("textbox", name=label),
                page.get_by_label(label),
                page.get_by_placeholder(label),
            ]
        )
    locators.extend(
        [
            page.locator("input[type='search']"),
            page.locator("[role='combobox'] input"),
            page.locator("[role='listbox'] input"),
            page.locator("input[aria-autocomplete]"),
        ]
    )
    for locator in locators:
        try:
            if _visible(locator, timeout_ms=1000):
                target = locator.last if locator.count() > 1 else locator.first
                target.fill(language, timeout=2500)
                return True
        except Exception:
            continue
    try:
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(language, delay=20)
        return True
    except Exception:
        return False


def click_data_language_option(page, language: str) -> bool:
    locators = [
        page.get_by_role("option", name=language, exact=True),
        page.get_by_text(language, exact=True),
        page.get_by_role("option", name=language),
        page.get_by_text(language, exact=False),
    ]
    if _click_visible(locators, timeout_ms=4000):
        return True
    try:
        page.keyboard.press("Enter")
        return True
    except Exception:
        return False


def select_data_languages(page, languages: list[str], log: Callable) -> list[str]:
    selected = []
    for language in normalize_data_languages(languages):
        if is_default_playground_language(language):
            log("info", "English mantido como padrao do Playground; clique ignorado.")
            continue
        if not open_data_languages_selector(page):
            log("warning", "Campo Data Languages nao abriu; tentando selecionar pelo texto visivel.")
        time.sleep(0.5)
        fill_data_language_search(page, language)
        time.sleep(0.5)
        if not click_data_language_option(page, language):
            raise PlaywrightAutomationError(f"Idioma nao encontrado em Data Languages: {language}")
        selected.append(language)
        log("info", f"Data Language selecionado: {language}")
        time.sleep(2)
    if selected:
        log("info", "Data Languages selecionado.", metadata={"languages": selected})
    return selected


def open_all_workspaces(page, log: Callable) -> None:
    if click_first(
        [lambda text=text: page.get_by_role("link", name=text) for text in ALL_WORKSPACE_TEXTS]
        + [lambda text=text: page.get_by_role("button", name=text) for text in ALL_WORKSPACE_TEXTS]
        + [lambda text=text: page.get_by_text(text, exact=False) for text in ALL_WORKSPACE_TEXTS],
        timeout_ms=2500,
    ):
        log("info", "All Workspace aberto.")
        return
    if any(text.lower() in page_text(page).lower() for text in ALL_WORKSPACE_TEXTS):
        log("info", "All Workspace ja estava visivel.")
        return
    raise WorkspaceNotFound("Nao foi possivel abrir All Workspace.")


def search_workspace(page, workspace_name: str, log: Callable) -> bool:
    filled = fill_first(
        [lambda term=term: page.get_by_placeholder(term) for term in WORKSPACE_FILTER_FIELDS]
        + [lambda term=term: page.get_by_label(term) for term in WORKSPACE_FILTER_FIELDS]
        + [lambda term=term: page.get_by_role("textbox", name=term) for term in WORKSPACE_FILTER_FIELDS]
        + [lambda: page.locator('input[type="search"]')],
        workspace_name,
        timeout_ms=4000,
    )
    if filled:
        log("info", f"Workspace pesquisado no Filter Workspace: {workspace_name}")
        time.sleep(2)
    return workspace_name.lower() in page_text(page).lower()


def workspace_page_is_stale(page) -> bool:
    body = page_text(page).lower()
    return (
        "reload now" in body
        or "please reload the page to update" in body
        or "new version of the application is available" in body
    )


def workspace_page_is_loading(page) -> bool:
    return "loading..." in page_text(page).lower()


def reload_workspace_page(page, log: Callable) -> None:
    clicked = click_first(
        [
            lambda: page.get_by_role("button", name="Reload Now"),
            lambda: page.get_by_text("Reload Now", exact=False),
        ],
        timeout_ms=1500,
    )
    if clicked:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        except Exception:
            pass
        return
    page.reload(wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)


def upload_area_present(page) -> bool:
    """Detecta a area de upload de forma independente do texto visivel.

    Alinhado com o que a acao de upload realmente usa (get_by_role / input file):
    um botao pode existir e ser clicavel mesmo que o rotulo esteja em aria-label
    (e nao no innerText do body) ou seja apenas um icone.
    """
    for text in UPLOAD_FILES_TEXTS + CHOOSE_FILES_TEXTS:
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


def workspace_area_loaded(page, expected_area: str) -> bool:
    expected_texts = WORKSPACE_EXPECTED_AREAS.get(expected_area)
    if not expected_texts:
        raise PlaywrightAutomationError(f"Area de Workspace invalida: {expected_area}")
    if workspace_page_is_stale(page) or workspace_page_is_loading(page):
        return False
    body = page_text(page).lower()
    if any(text.lower() in body for text in expected_texts):
        return True
    if expected_area == "upload" and upload_area_present(page):
        return True
    return False


def wait_for_workspace_area(page, expected_area: str, timeout_ms: int = 20000) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if workspace_area_loaded(page, expected_area):
            return True
        time.sleep(0.5)
    return False


def workspace_link_href(page, workspace_name: str) -> str | None:
    candidates = [
        page.get_by_role("link", name=workspace_name),
        page.locator("a").filter(has_text=workspace_name),
    ]
    for locator in candidates:
        count = min(_count(locator), 10)
        for index in range(count):
            candidate = locator.nth(index)
            try:
                text = candidate.inner_text(timeout=1000).strip()
            except Exception:
                text = ""
            if text and workspace_name.lower() not in text.lower():
                continue
            try:
                href = candidate.get_attribute("href", timeout=1000)
            except Exception:
                href = None
            if href and not href.strip().lower().startswith(("javascript:", "#")):
                return href
    return None


def open_workspace_by_href(page, workspace_name: str, log: Callable) -> bool:
    href = workspace_link_href(page, workspace_name)
    if not href:
        return False
    target_url = urljoin(page.url, href)
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        log("info", "Workspace aberto pelo link direto da listagem.", metadata={"workspace_href": href})
        return True
    except Exception as exc:
        log("warning", "Falha ao abrir Workspace pelo link direto; tentando clique visivel.", metadata={"error": str(exc)})
        return False


def click_workspace_option(page, workspace_name: str, log: Callable) -> bool:
    locators = [
        page.get_by_role("option", name=workspace_name, exact=True),
        page.locator("[role='option']").filter(has_text=workspace_name),
        page.get_by_role("option", name=workspace_name),
    ]
    for locator in locators:
        count = min(_count(locator), 5)
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible(timeout=1000):
                    candidate.click(timeout=4000)
                    log("info", "Workspace selecionado pela opcao visivel do filtro.")
                    return True
            except Exception:
                continue
    try:
        if _count(page.locator("[role='option']").filter(has_text=workspace_name)):
            page.keyboard.press("Enter")
            log("info", "Workspace selecionado via Enter no filtro.")
            return True
    except Exception:
        pass
    return False


def select_workspace_from_list(page, workspace_name: str, log: Callable) -> bool:
    log("info", "Abrindo All Workspace.")
    open_all_workspaces(page, log)
    log("info", f"Pesquisando Workspace pelo nome do dashboard: {workspace_name}")
    if not search_workspace(page, workspace_name, log):
        return False

    if open_workspace_by_href(page, workspace_name, log):
        return True
    if click_workspace_option(page, workspace_name, log):
        return True

    try:
        return click_first(
            [
                lambda: page.get_by_role("link", name=workspace_name),
                lambda: page.get_by_role("button", name=workspace_name),
                lambda: page.get_by_text(workspace_name, exact=True),
                lambda: page.get_by_text(workspace_name, exact=False),
            ],
            timeout_ms=4000,
        )
    except Exception as exc:
        log("warning", "Clique no Workspace foi interceptado pela listagem; tentando abrir pelo link novamente.", metadata={"error": str(exc)})
        return open_workspace_by_href(page, workspace_name, log)


def open_workspace(page, workspace_name: str, log: Callable, expected_area: str = "upload") -> None:
    if expected_area not in WORKSPACE_EXPECTED_AREAS:
        raise PlaywrightAutomationError(f"Area de Workspace invalida: {expected_area}")

    for attempt in range(1, 3):
        clicked = select_workspace_from_list(page, workspace_name, log)
        if not clicked:
            if attempt < 2:
                log("warning", f"Workspace nao encontrado na tentativa {attempt}; recarregando listagem.")
                page.reload(wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
                continue
            raise WorkspaceNotFound(f"Workspace nao encontrado na listagem: {workspace_name}")

        if workspace_page_is_stale(page):
            log("warning", "Workspace ficou em Loading; recarregando.")
            reload_workspace_page(page, log)
            continue

        log("info", f"Workspace aberto: {workspace_name}")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        if wait_for_workspace_area(page, expected_area, timeout_ms=settings.WORKSPACE_AREA_TIMEOUT_MS):
            log("info", WORKSPACE_AREA_LOGS[expected_area])
            return
        if attempt < 2:
            log("warning", "Area esperada do Workspace nao carregou; recarregando.")
            if workspace_page_is_stale(page) or workspace_page_is_loading(page):
                log("warning", "Workspace ficou em Loading; recarregando.")
            page.reload(wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
            continue
        raise WorkspaceNotFound(f"Workspace abriu, mas a area esperada ({expected_area}) nao carregou: {workspace_name}")


def capture_workspace_id(url: str) -> str | None:
    for pattern in [r"/workspaces?/([^/?#]+)", r"workspaceId=([^&#]+)", r"workspace_id=([^&#]+)"]:
        match = re.search(pattern, url or "", flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def click_create_workspace(page, log: Callable) -> None:
    clicked = click_first(
        [lambda text=text: page.get_by_role("button", name=text) for text in CREATE_WORKSPACE_TEXTS]
        + [lambda text=text: page.get_by_role("link", name=text) for text in CREATE_WORKSPACE_TEXTS]
        + [lambda text=text: page.get_by_text(text, exact=False) for text in CREATE_WORKSPACE_TEXTS],
        timeout_ms=5000,
    )
    if not clicked:
        raise PlaywrightAutomationError("Botao Create Workspace nao encontrado.")
    log("info", "Criacao de Workspace iniciada.")


def click_final_create_workspace(page) -> None:
    for text in CREATE_WORKSPACE_TEXTS:
        try:
            locator = page.get_by_role("button", name=text)
            if locator.count():
                locator.last.click(timeout=5000)
                return
        except Exception:
            pass
    for text in CREATE_WORKSPACE_TEXTS:
        try:
            locator = page.get_by_text(text, exact=False)
            if locator.count():
                locator.last.click(timeout=5000)
                return
        except Exception:
            pass
    raise PlaywrightAutomationError("Botao final Create Workspace nao encontrado.")


def create_playground_workspace(
    task_id: int,
    user_id: int | None,
    payload: dict[str, Any],
    log: Callable,
) -> dict[str, Any]:
    workspace_name = str(payload.get("workspace_name") or payload.get("name") or "").strip()
    if not workspace_name:
        raise PlaywrightAutomationError("Payload sem workspace_name.")

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
        ensure_logged_in(page, payload, log)
        open_all_workspaces(page, log)
        click_create_workspace(page, log)
        fill_field(page, WORKSPACE_NAME_FIELDS, workspace_name, required=True)
        log("info", "Workspace Name preenchido.")
        fill_field(page, WORKSPACE_DESCRIPTION_FIELDS, str(payload.get("description") or ""), required=False)
        if payload.get("description"):
            log("info", "Description preenchida.")
        if payload.get("embedding_model"):
            select_option(page, EMBEDDING_MODEL_FIELDS, str(payload["embedding_model"]), required=False)
            log("info", "Embeddings Model selecionado.")
        data_languages = select_data_languages(page, payload.get("data_languages"), log)

        click_final_create_workspace(page)
        log("info", "Create Workspace final clicado.")
        if not wait_for_text(page, [workspace_name, "created", "success"], timeout_ms=30000):
            raise PlaywrightAutomationError("Workspace nao apareceu apos a criacao.")

        # URL imediata logo apos a criacao, usada como fallback caso a captura da
        # URL direta (abaixo) nao consiga reabrir o workspace recem-criado.
        playground_url = page.url
        log("info", "Workspace criado.")

        # Novo fluxo: aguarda o Playground persistir o workspace, recarrega a listagem,
        # pesquisa pelo nome recem-criado, abre o workspace e captura a URL direta dele
        # (a URL "local" do workspace), para salvar no dashboard e permitir abrir
        # diretamente por ela nos uploads seguintes.
        try:
            log("info", "Aguardando 10s antes de capturar a URL direta do workspace.")
            time.sleep(10)
            page.reload(wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
            open_workspace(page, workspace_name, log, expected_area="upload")
            playground_url = page.url
            log("info", "URL direta do workspace capturada.", metadata={"playground_url": playground_url})
        except Exception as exc:
            log(
                "warning",
                "Nao foi possivel capturar a URL direta apos recarregar; mantendo a URL imediata da criacao.",
                metadata={"error": str(exc), "playground_url": playground_url},
            )

        return {
            "workspace_id": payload.get("workspace_id"),
            "workspace_name": workspace_name,
            "playground_workspace_id": capture_workspace_id(playground_url),
            "playground_url": playground_url,
            "embedding_model": payload.get("embedding_model"),
            "data_languages": data_languages,
            "created_via": "automation",
            "status": "active",
        }
    except Exception:
        if browser and browser.page:
            safe_error_screenshot(browser.page, task_id, log)
        raise
    finally:
        if browser:
            browser.close()
            log("info", "Navegador fechado.")
