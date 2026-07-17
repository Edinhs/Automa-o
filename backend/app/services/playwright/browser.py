from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

from app.core.config import runtime_path, settings


def session_dir_for_user(user_id: Optional[int]) -> Path:
    if user_id in [None, ""]:
        raise ValueError("user_id e obrigatorio para abrir sessao persistente do Chromium.")
    user_folder = f"user_{user_id}"
    path = runtime_path("BROWSER_SESSION_PATH") / user_folder
    path.mkdir(parents=True, exist_ok=True)
    return path


def screenshots_error_dir() -> Path:
    path = runtime_path("SCREENSHOTS_ERROR_PATH")
    path.mkdir(parents=True, exist_ok=True)
    return path


def launch_channel_for(channel: Optional[str]) -> Optional[str]:
    normalized = (channel or "").strip().lower()
    if normalized in ["", "chromium", "default", "none"]:
        return None
    return normalized


def save_error_screenshot(page, task_id: int) -> Optional[Path]:
    if page is None:
        return None
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = screenshots_error_dir() / f"task_{task_id}_{timestamp}.png"
    page.screenshot(path=str(path), full_page=True)
    return path


def safe_error_screenshot(page, task_id: int, log: Callable | None = None) -> Optional[Path]:
    try:
        path = save_error_screenshot(page, task_id)
        if path and log:
            try:
                log("error", f"Screenshot salvo: {path}", metadata={"screenshot_path": str(path)})
            except TypeError:
                log("error", f"Screenshot salvo: {path}")
        return path
    except Exception as exc:
        if log:
            try:
                log("warning", f"Falha ao salvar screenshot de erro: {exc}")
            except TypeError:
                pass
        return None


@dataclass
class PersistentBrowser:
    playwright: object
    context: object
    page: object
    session_dir: Path

    def close(self) -> None:
        try:
            self.context.close()
        finally:
            self.playwright.stop()


def open_persistent_chromium(
    user_id: Optional[int],
    *,
    headless: Optional[bool] = None,
    browser_channel: Optional[str] = None,
    session_dir: Optional[Path] = None,
) -> PersistentBrowser:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Playwright nao instalado. Execute: cd backend && .venv\\Scripts\\activate && "
            "pip install -r requirements.txt && python -m playwright install chromium"
        ) from exc

    if session_dir is None:
        session_dir = session_dir_for_user(user_id)
    playwright = sync_playwright().start()
    launch_options = {
        "user_data_dir": str(session_dir),
        "headless": settings.PLAYWRIGHT_HEADLESS if headless is None else bool(headless),
        "viewport": None,
        "args": ["--start-maximized"],
    }
    channel = launch_channel_for(browser_channel or settings.PLAYGROUND_BROWSER_CHANNEL)
    if channel:
        launch_options["channel"] = channel

    context = playwright.chromium.launch_persistent_context(**launch_options)
    context.set_default_timeout(settings.PLAYWRIGHT_DEFAULT_TIMEOUT)
    page = context.pages[0] if context.pages else context.new_page()
    return PersistentBrowser(
        playwright=playwright,
        context=context,
        page=page,
        session_dir=session_dir,
    )


def first_visible(locator_factories: Iterable[Callable], timeout_ms: int = 1500):
    for locator_factory in locator_factories:
        try:
            locator = locator_factory()
            first = locator.first
            if first.count() and first.is_visible(timeout=timeout_ms):
                return first
        except Exception:
            continue
    return None


def click_first(locator_factories: Iterable[Callable], timeout_ms: int = 3000) -> bool:
    locator = first_visible(locator_factories, timeout_ms=timeout_ms)
    if not locator:
        return False
    locator.click(timeout=timeout_ms)
    return True


def fill_first(locator_factories: Iterable[Callable], value: str, timeout_ms: int = 3000) -> bool:
    locator = first_visible(locator_factories, timeout_ms=timeout_ms)
    if not locator:
        return False
    locator.fill(value, timeout=timeout_ms)
    return True


def wait_for_text(page, texts: list[str], timeout_ms: Optional[int] = None) -> bool:
    deadline = time.monotonic() + ((timeout_ms or settings.PLAYWRIGHT_DEFAULT_TIMEOUT) / 1000)
    while time.monotonic() < deadline:
        body = page_text(page).lower()
        if any(text.lower() in body for text in texts):
            return True
        time.sleep(0.5)
    return False


def page_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def retry_action(action: Callable[[], object], retries: int = 3, delay_seconds: float = 1.0):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return action()
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay_seconds)
    raise last_error
