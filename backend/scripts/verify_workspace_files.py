r"""
verify_workspace_files.py -- Verificacao READ-ONLY definitiva de quais arquivos
existem num workspace, usando (1) leitura estabilizada da tabela e (2) o campo de
busca do Playground (mais confiavel que so ler a tabela paginada).

NAO clica em deletar nem em nada destrutivo. Apenas digita no campo de busca e le.

Uso:
    $env:INSPECT_WORKSPACE_URL = "https://genai.stellantis.com/rag/workspaces/<id>"
    & ".\backend\.venv\Scripts\python.exe" ".\backend\scripts\verify_workspace_files.py"
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
    for cand in (BACKEND_DIR / "ms-playwright",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"):
        if cand.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cand)
            print(f"[INFO] PLAYWRIGHT_BROWSERS_PATH -> {cand}")
            return
    print("[WARN] ms-playwright nao encontrado.")


_set_browsers_path()

_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_env_file))
    except ImportError:
        pass

from app.services.playwright.browser import open_persistent_chromium  # noqa: E402
from app.services.playwright.playground_login import is_logged_in  # noqa: E402
from app.services.playwright.playground_monitor import (  # noqa: E402
    open_files_tab,
    iter_page_file_rows,
    goto_next_files_page,
    find_files_search_field,
    wait_for_files_table_stable,
)

USER_ID = int(os.environ.get("INSPECT_USER_ID", "1"))
WORKSPACE_URL = os.environ.get(
    "INSPECT_WORKSPACE_URL",
    "https://genai.stellantis.com/rag/workspaces/44285aae-872d-442d-9943-0147f71b01fc",
)
QUERIES = ["PRESENT", "Exercicio", "CONTRATO", "Diagrama", "HOMEWORK"]


def _log(level: str, message: str, **_kw) -> None:
    print(f"[{level.upper()}] {message}")


def _list_all_rows(page) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    wait_for_files_table_stable(page, should_continue=None, timeout_seconds=15)
    for _r, name, status in iter_page_file_rows(page):
        if name and name not in seen:
            seen.add(name)
            pairs.append((name, status))
    for _pg in range(6):
        if not goto_next_files_page(page):
            break
        time.sleep(0.5)
        wait_for_files_table_stable(page, should_continue=None, timeout_seconds=10)
        for _r, name, status in iter_page_file_rows(page):
            if name and name not in seen:
                seen.add(name)
                pairs.append((name, status))
    return pairs


def main() -> None:
    print(f"\n[INFO] Abrindo Chromium (user {USER_ID}) -> {WORKSPACE_URL}")
    browser = open_persistent_chromium(USER_ID)
    page = browser.page
    try:
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        if not is_logged_in(page):
            print("[WARN] Sessao NAO logada. Abortando.")
            return
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                open_files_tab(page, _log)
                break
            except Exception:
                time.sleep(2)
        time.sleep(2)

        print("\n=== 1) LISTAGEM ESTABILIZADA DE TODAS AS LINHAS ===")
        rows = _list_all_rows(page)
        for name, status in rows:
            print(f"  '{name}' | {status}")
        print(f"  Total: {len(rows)} arquivo(s)")

        print("\n=== 2) BUSCA NO CAMPO DE PESQUISA DO PLAYGROUND ===")
        field = find_files_search_field(page)
        if field is None:
            print("[WARN] Campo de busca nao encontrado; pulando etapa 2.")
        else:
            for q in QUERIES:
                try:
                    field.fill("")
                    time.sleep(0.4)
                    field.fill(q)
                    time.sleep(1.0)
                    wait_for_files_table_stable(page, should_continue=None, timeout_seconds=8)
                    hits = []
                    for _r, name, status in iter_page_file_rows(page):
                        if name:
                            hits.append(f"{name} [{status}]")
                    print(f"  busca '{q}': {hits if hits else 'NENHUM resultado'}")
                except Exception as exc:
                    print(f"  busca '{q}': ERRO {exc}")
            try:
                field.fill("")
            except Exception:
                pass

        print("\n[INFO] Verificacao concluida (somente leitura).")
    finally:
        browser.close()
        print("[INFO] Navegador fechado.")


if __name__ == "__main__":
    main()
