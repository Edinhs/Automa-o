from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from app.core.config import normalize_url, settings
from app.services.playwright.browser import (
    click_first,
    fill_first,
    open_persistent_chromium,
    page_text,
    safe_error_screenshot,
)
from app.services.playwright.errors import (
    PlaygroundConfigurationError,
    PlaygroundLoginRequired,
    PlaygroundLoginTimeout,
)
from app.services.playwright.selectors import (
    LOGGED_IN_TEXTS,
    LOGIN_TEXTS,
    LOGIN_URL_MARKERS,
    NETWORK_ID_FIELDS,
    STELLANTIS_LOGIN_TEXTS,
)


@dataclass
class PlaygroundConnectResult:
    connected: bool
    already_connected: bool
    session_path: str
    screenshot_path: str | None = None


def configured_playground_url(payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    raw_url = str(payload.get("url") or payload.get("playground_url") or settings.PLAYGROUND_URL or "").strip()
    url = normalize_url(raw_url)
    if not url or "COLOQUE_A_URL_DO_PLAYGROUND_AQUI" in url:
        raise PlaygroundConfigurationError(
            "PLAYGROUND_URL nao configurada. Defina PLAYGROUND_URL no backend/.env."
        )
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PlaygroundConfigurationError(
            f"PLAYGROUND_URL invalida: {url}. Use uma URL completa, por exemplo https://genai.stellantis.com/."
        )
    return url


def has_password_field(page) -> bool:
    try:
        return page.locator('input[type="password"]').count() > 0
    except Exception:
        return False


def looks_like_login_url(url: str) -> bool:
    normalized = (url or "").lower()
    return any(marker in normalized for marker in LOGIN_URL_MARKERS)


def is_logged_in(page) -> bool:
    text = page_text(page)
    current_url = (page.url or "").lower()
    lower_text = text.lower()
    logged_marker = any(marker.lower() in lower_text for marker in LOGGED_IN_TEXTS)
    login_marker = any(marker.lower() in lower_text for marker in LOGIN_TEXTS)
    if has_password_field(page):
        return False
    if logged_marker and not looks_like_login_url(current_url):
        return True
    if logged_marker and not login_marker:
        return True
    return False


def click_stellantis_login_if_visible(page, log: Callable) -> bool:
    clicked = click_first(
        [
            lambda text=text: page.get_by_role("button", name=text)
            for text in STELLANTIS_LOGIN_TEXTS
        ]
        + [
            lambda text=text: page.get_by_text(text, exact=False)
            for text in STELLANTIS_LOGIN_TEXTS
        ],
        timeout_ms=2500,
    )
    if clicked:
        log("info", "Stellantis Login clicado.")
    return clicked


def fill_network_id_if_possible(page, payload: dict[str, Any], log: Callable) -> bool:
    network_id = (
        payload.get("network_id")
        or payload.get("user_identifier")
        or payload.get("external_user_id")
        or payload.get("requested_by")
    )
    if not network_id:
        return False
    value = str(network_id).strip()
    if not value:
        return False
    filled = fill_first(
        [
            lambda label=label: page.get_by_label(label)
            for label in NETWORK_ID_FIELDS
        ]
        + [
            lambda placeholder=placeholder: page.get_by_placeholder(placeholder)
            for placeholder in NETWORK_ID_FIELDS
        ]
        + [
            lambda: page.locator('input[type="email"]'),
            lambda: page.locator('input[name*="user" i]'),
            lambda: page.locator('input[name*="login" i]'),
        ],
        value,
        timeout_ms=2500,
    )
    if filled:
        log("info", "ID de rede informado no login.")
    return filled


def wait_for_login_completion(
    page,
    log: Callable,
    timeout_minutes: int | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> None:
    # timeout_minutes (e settings.MANUAL_LOGIN_TIMEOUT_MINUTES) ficam por compatibilidade de
    # assinatura, mas sao IGNORADOS de proposito: o dono quer esperar INDEFINIDAMENTE pelo login
    # manual, sem NUNCA cair em erro por timeout. O unico jeito de abortar e o botao "parar"
    # (should_continue levanta a excecao de parada -> a task vira "cancelled", nao "failed").
    log("warning", "Login manual necessario: conclua o login no Chromium aberto para continuar a automacao.")
    iteration = 0
    while True:
        # Deixa o botao "parar" interromper o login manual (unica saida alem do login concluido).
        if should_continue:
            should_continue()
        if is_logged_in(page):
            log("info", "Login confirmado.")
            return
        iteration += 1
        # Lembrete periodico (~a cada 30s = 6 iteracoes de 5s) para o dono nao achar que travou.
        if iteration % 6 == 0:
            log("info", "Aguardando login manual no Chromium aberto... (a automacao continua esperando)")
        time.sleep(5)


def ensure_logged_in(
    page,
    payload: dict[str, Any],
    log: Callable,
    should_continue: Callable[[], bool] | None = None,
) -> bool:
    if is_logged_in(page):
        log("info", "Sessao ja conectada.")
        return True
    click_stellantis_login_if_visible(page, log)
    fill_network_id_if_possible(page, payload, log)
    # Se ainda nao logou e o navegador esta headless (invisivel), nao adianta esperar o login
    # manual: sinaliza para o agente reabrir o Chromium de forma VISIVEL e repetir a tarefa.
    if not is_logged_in(page) and bool(payload.get("headless")):
        raise PlaygroundLoginRequired(
            "Login manual necessario, mas o navegador esta em modo headless (invisivel). "
            "Reabrindo o Chromium de forma visivel para o login."
        )
    wait_for_login_completion(page, log, payload.get("manual_login_timeout_minutes"), should_continue)
    return False


def connect_playground_session(
    task_id: int,
    user_id: int | None,
    log: Callable,
    payload: dict[str, Any] | None = None,
    should_continue: Callable[[], bool] | None = None,
) -> PlaygroundConnectResult:
    payload = payload or {}
    url = configured_playground_url(payload)
    browser = None
    try:
        log("info", "Chromium iniciado.")
        browser = open_persistent_chromium(
            user_id,
            headless=payload.get("headless"),
            browser_channel=payload.get("browser_channel"),
        )
        log("info", f"Caminho de sessao usado: {browser.session_dir}")
        page = browser.page
        log("info", "Playground acessado.")
        page.goto(url, wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
        if should_continue:
            should_continue()

        already_connected = is_logged_in(page)
        if already_connected:
            log("info", "Sessao ja conectada.")
        else:
            click_stellantis_login_if_visible(page, log)
            fill_network_id_if_possible(page, payload, log)
            # Mesma logica de ensure_logged_in: headless + nao logado -> sinaliza retry visivel.
            if not is_logged_in(page) and bool(payload.get("headless")):
                raise PlaygroundLoginRequired(
                    "Login manual necessario, mas o navegador esta em modo headless (invisivel). "
                    "Reabrindo o Chromium de forma visivel para o login."
                )
            wait_for_login_completion(page, log, payload.get("manual_login_timeout_minutes"), should_continue)

        log("info", "Sessao salva.")
        return PlaygroundConnectResult(
            connected=True,
            already_connected=already_connected,
            session_path=str(browser.session_dir),
        )
    except Exception:
        if browser and browser.page:
            safe_error_screenshot(browser.page, task_id, log)
        raise
    finally:
        if browser:
            browser.close()
            log("info", "Navegador fechado.")
