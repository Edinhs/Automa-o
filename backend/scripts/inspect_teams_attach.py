r"""
inspect_teams_attach.py -- READ-ONLY live DOM inspection of the Teams Web compose toolbar.

Goal: find the real selector(s) needed to attach a local file to a Teams Web (v2) chat
message via Playwright, since `input[type="file"]` is NOT present in the DOM until the
user interacts with an "Attach" control (paperclip / "+" icon) in the compose toolbar.

Uses the SAME persistent Chromium session (TEAMS_BROWSER_SESSION_PATH/user_{id}) as the
real delivery flow (app/services/playwright/teams_delivery.py), so it reuses the existing
login -- no new SSO needed if the real flow already worked once.

Usage (from backend dir):
    .venv\\Scripts\\python.exe scripts\\inspect_teams_attach.py

Environment overrides:
    INSPECT_USER_ID (default 1)
    INSPECT_CHAT_NAME (default "1:1 Ederson")
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _set_browsers_path() -> None:
    existing = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if existing and Path(existing).exists():
        return
    local_msp = BACKEND_DIR / "ms-playwright"
    if local_msp.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_msp)
        return
    appdata = Path(os.environ.get("LOCALAPPDATA", "C:/Users/Default/AppData/Local"))
    appdata_msp = appdata / "ms-playwright"
    if appdata_msp.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(appdata_msp)


_set_browsers_path()

_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

from app.core.config import runtime_path, settings  # noqa: E402
from app.services.playwright.browser import open_persistent_chromium  # noqa: E402
from app.services.playwright.teams_delivery import (  # noqa: E402
    is_teams_logged_in,
    navigate_to_chat,
)

USER_ID = int(os.environ.get("INSPECT_USER_ID", "1"))
CHAT_NAME = os.environ.get("INSPECT_CHAT_NAME", "1:1 Ederson")
TEAMS_URL = settings.TEAMS_WEB_URL or "https://teams.microsoft.com/v2/"


def log(level: str, message: str) -> None:
    print(f"[{level.upper()}] {message}", flush=True)


def main() -> None:
    session_dir = runtime_path("TEAMS_BROWSER_SESSION_PATH")
    log("info", f"Session dir: {session_dir}")
    browser = open_persistent_chromium(user_id=USER_ID, headless=False, session_dir=session_dir)
    page = browser.page
    try:
        page.goto(TEAMS_URL, wait_until="domcontentloaded")
        time.sleep(5)
        log("info", f"Logged in? {is_teams_logged_in(page)}")
        navigate_to_chat(page, CHAT_NAME, log)

        shot_path = BACKEND_DIR / "data" / "screenshots" / "teams_inspect_before.png"
        shot_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shot_path), full_page=False)
        log("info", f"Screenshot saved: {shot_path}")

        # Dump every button/toolbar item near the compose box with any identifying attribute.
        candidates = page.evaluate(
            """
            () => {
                const results = [];
                const nodes = document.querySelectorAll('button, [role="button"]');
                nodes.forEach((el) => {
                    const label = (el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || '').trim();
                    if (!label) return;
                    const lower = label.toLowerCase();
                    if (lower.includes('attach') || lower.includes('anexar') || lower.includes('upload') ||
                        lower.includes('carregar') || lower.includes('mais a') || lower.includes('more act') ||
                        lower.includes('file') || lower.includes('arquivo')) {
                        results.push({
                            label,
                            tid: el.getAttribute('data-tid') || null,
                            tag: el.tagName,
                            visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                        });
                    }
                });
                return results;
            }
            """
        )
        log("info", f"Candidatos encontrados: {len(candidates)}")
        for c in candidates:
            print(f"  - {c}")

        # Click the Attach button and dump the resulting menu items.
        try:
            page.locator('[data-tid="sendMessageCommands-FilePicker"]').first.click(timeout=5000)
            time.sleep(2)
            menu_items = page.evaluate(
                """
                () => {
                    const results = [];
                    document.querySelectorAll('[role="menuitem"], [role="menuitemradio"], li').forEach((el) => {
                        const label = (el.getAttribute('aria-label') || el.innerText || '').trim();
                        if (label) results.push({label, tid: el.getAttribute('data-tid') || null});
                    });
                    return results;
                }
                """
            )
            print("---- MENU ITEMS AFTER CLICKING 'Anexar arquivos' ----")
            for item in menu_items:
                print(f"  - {item}")
            shot_path2 = BACKEND_DIR / "data" / "screenshots" / "teams_inspect_menu.png"
            page.screenshot(path=str(shot_path2), full_page=False)
            log("info", f"Menu screenshot saved: {shot_path2}")
        except Exception as exc:
            log("warning", f"Falha ao clicar em Anexar arquivos: {exc}")

        # Also dump ALL toolbar buttons (compose area) regardless of label match, capped.
        all_buttons = page.evaluate(
            """
            () => {
                const results = [];
                document.querySelectorAll('button, [role="button"]').forEach((el) => {
                    const label = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                    if (label) results.push(label);
                });
                return results;
            }
            """
        )
        print("---- ALL BUTTON LABELS (deduped) ----")
        for label in sorted(set(all_buttons)):
            print(f"  * {label}")

        time.sleep(5)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
