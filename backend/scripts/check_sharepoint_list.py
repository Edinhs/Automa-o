r"""Abre a lista do SharePoint informada pelo usuario para inspecionar as colunas
existentes (necessario para montar o formulario e a acao Create item no Power Automate)."""
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


_set_browsers_path()
_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

from app.core.config import runtime_path  # noqa: E402
from app.services.playwright.browser import open_persistent_chromium  # noqa: E402

LIST_URL = (
    "https://shiftup.sharepoint.com/sites/StellantisAutomationHub/Lists/"
    "Solicitaes%20de%20Acesso%20a%20Workspace/AllItems.aspx"
)


def main():
    session_dir = runtime_path("TEAMS_BROWSER_SESSION_PATH")
    browser = open_persistent_chromium(user_id=1, headless=False, session_dir=session_dir)
    page = browser.page
    try:
        page.goto(LIST_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(6)
        out = BACKEND_DIR / "data" / "screenshots" / "sharepoint_list_check.png"
        page.screenshot(path=str(out), full_page=False)
        print("URL atual:", page.url)
        print("Titulo:", page.title())
        print("Screenshot:", out)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
