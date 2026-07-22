r"""
test_teams_png_send.py -- Manual, one-off validation of the FIXED attachment flow in
app/services/playwright/teams_delivery.py (attach_files_via_picker). Sends one PNG file to
the configured Teams chat and takes an after-send screenshot for visual confirmation.

Usage (from backend dir):
    .venv\\Scripts\\python.exe scripts\\test_teams_png_send.py <path_to_png>
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


_set_browsers_path()

_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

from app.services.playwright.teams_delivery import deliver_file_teams_playwright  # noqa: E402
from app.core.config import runtime_path  # noqa: E402


def log(level: str, message: str, **kwargs) -> None:
    print(f"[{level.upper()}] {message}", flush=True)


def main() -> None:
    png_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not png_path or not Path(png_path).exists():
        print("Uso: test_teams_png_send.py <caminho_para_png_existente>")
        sys.exit(1)

    payload = {
        "file_path": png_path,
        "chat_name": "1:1 Ederson",
        "text_message": f"[TESTE VALIDACAO] Imagem anexada de verdade: {Path(png_path).name}",
        "headless": False,
    }
    result = deliver_file_teams_playwright(payload=payload, log=log, task_id=999999, user_id=1)
    print("RESULT:", result)


if __name__ == "__main__":
    main()
