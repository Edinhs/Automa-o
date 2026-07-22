r"""Quick screenshot of the target Teams chat (read-only, no interaction) to visually
confirm a previously sent attachment landed correctly."""
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

from app.core.config import runtime_path, settings  # noqa: E402
from app.services.playwright.browser import open_persistent_chromium  # noqa: E402
from app.services.playwright.teams_delivery import navigate_to_chat  # noqa: E402


def log(level, message):
    print(f"[{level.upper()}] {message}", flush=True)


def main():
    session_dir = runtime_path("TEAMS_BROWSER_SESSION_PATH")
    browser = open_persistent_chromium(user_id=1, headless=False, session_dir=session_dir)
    page = browser.page
    try:
        page.goto(settings.TEAMS_WEB_URL or "https://teams.microsoft.com/v2/", wait_until="domcontentloaded")
        time.sleep(4)
        navigate_to_chat(page, "1:1 Ederson", log)
        time.sleep(3)
        out = BACKEND_DIR / "data" / "screenshots" / "teams_after_send_confirm.png"
        page.screenshot(path=str(out), full_page=False)
        print("Screenshot:", out)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
