r"""Le todos os cabecalhos de coluna da lista do SharePoint via DOM (columnheader),
sem depender de scroll visual, e tambem tenta abrir o formulario Novo em painel."""
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
        time.sleep(5)
        headers = page.locator("[role='columnheader']").all_inner_texts()
        print("COLUNAS:", headers)

        # Abre o item "Novo" via botao no topo
        try:
            page.locator("button:has-text('Novo')").first.click(timeout=8000)
            time.sleep(3)
            out2 = BACKEND_DIR / "data" / "screenshots" / "sharepoint_list_new_form.png"
            page.screenshot(path=str(out2), full_page=True)
            print("Screenshot formulario Novo:", out2)
        except Exception as exc:
            print("Nao consegui abrir o formulario Novo:", exc)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
