r"""
realrun_monitor_rowbyrow.py -- Execucao REAL (dry_run=False) do monitor linha a linha.

ATENCAO: este script DELETA DE VERDADE arquivos Error/Processing no workspace alvo,
usando exatamente a logica do monitor (delete_one_with_verify, com verificacao por F5).
Os arquivos Ready NUNCA sao deletados (GUARDA central). Ao final, reabre a tabela e
verifica que:
  - todo arquivo que estava Ready continua presente e Ready (nenhum Ready perdido);
  - os arquivos Error/Processing escolhidos para delete sumiram (DELETE_DELETED).

Uso (a partir da raiz do repo):
    $env:INSPECT_WORKSPACE_URL = "https://genai.stellantis.com/rag/workspaces/<id>"
    & ".\backend\.venv\Scripts\python.exe" ".\backend\scripts\realrun_monitor_rowbyrow.py"
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
        print(f"[INFO] PLAYWRIGHT_BROWSERS_PATH ja definido: {existing}")
        return
    local_msp = BACKEND_DIR / "ms-playwright"
    if local_msp.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_msp)
        print(f"[INFO] PLAYWRIGHT_BROWSERS_PATH -> {local_msp}")
        return
    appdata = Path(os.environ.get("LOCALAPPDATA", "C:/Users/Default/AppData/Local"))
    appdata_msp = appdata / "ms-playwright"
    if appdata_msp.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(appdata_msp)
        print(f"[INFO] PLAYWRIGHT_BROWSERS_PATH -> {appdata_msp} (AppData fallback)")
        return
    print("[WARN] ms-playwright nao encontrado.")


_set_browsers_path()

_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_env_file))
        print(f"[INFO] .env carregado de {_env_file}")
    except ImportError:
        print("[WARN] python-dotenv nao instalado; .env nao carregado.")

from app.services.playwright.browser import open_persistent_chromium  # noqa: E402
from app.services.playwright.playground_login import is_logged_in  # noqa: E402
from app.services.playwright.playground_workspace import wait_for_workspace_area  # noqa: E402
from app.services.playwright.playground_monitor import (  # noqa: E402
    open_files_tab,
    iter_page_file_rows,
    _stream_read_and_delete,
    f5_reopen_files,
    goto_next_files_page,
    read_all_pages_statuses,
    wait_for_files_table_stable,
    DELETE_DELETED, DELETE_WOULD_DELETE, DELETE_SKIPPED_READY,
    DELETE_SKIPPED_STATUS, DELETE_ABSENT, DELETE_AMBIGUOUS, DELETE_FAILED,
)

USER_ID = int(os.environ.get("INSPECT_USER_ID", "1"))
WORKSPACE_URL = os.environ.get(
    "INSPECT_WORKSPACE_URL",
    "https://genai.stellantis.com/rag/workspaces/44285aae-872d-442d-9943-0147f71b01fc",
)

_log_lines: list[str] = []


def _log(level: str, message: str, **_kw) -> None:
    line = f"[{level.upper()}] {message}"
    print(line)
    _log_lines.append(line)


def _collect_rows(page) -> list[tuple[str, str]]:
    """Coleta (nome, status) de todas as paginas, esperando a tabela estabilizar."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    wait_for_files_table_stable(page, should_continue=None, timeout_seconds=15)
    for _row, name, status in iter_page_file_rows(page):
        if name and name not in seen:
            seen.add(name)
            pairs.append((name, status))
    for _pg in range(8):
        if not goto_next_files_page(page):
            break
        time.sleep(0.5)
        wait_for_files_table_stable(page, should_continue=None, timeout_seconds=10)
        for _row, name, status in iter_page_file_rows(page):
            if name and name not in seen:
                seen.add(name)
                pairs.append((name, status))
    return pairs


def main() -> None:
    print(f"\n[INFO] Abrindo Chromium persistente para user_id={USER_ID}")
    browser = open_persistent_chromium(USER_ID)
    page = browser.page

    payload = {
        "workspace_playground_url": WORKSPACE_URL,
        "url": "https://genai.stellantis.com/",
        "workspace_name": "workspace-realrun-test",
        "files": [],
        "manual_login_timeout_minutes": int(os.environ.get("INSPECT_LOGIN_MIN", "4")),
    }

    try:
        print(f"[INFO] Navegando para: {WORKSPACE_URL}")
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        if not is_logged_in(page):
            print("\n[WARN] Sessao NAO esta logada. Login manual necessario antes do teste.")
            return

        print("[INFO] Sessao logada.")
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        try:
            wait_for_workspace_area(page, "files", timeout_ms=20000)
        except Exception:
            pass

        print("[INFO] Abrindo aba Files...")
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                open_files_tab(page, _log)
                break
            except Exception:
                time.sleep(2)
        time.sleep(2)

        # --- Estado ANTES ---
        print("\n[INFO] Estado ANTES do teste:")
        before = _collect_rows(page)
        for name, status in before:
            print(f"  '{name}' | status='{status}'")
        ready_before = {n for n, s in before if s == "Ready"}
        to_delete_before = {n for n, s in before if s in ("Error", "Processing")}
        expected_names = [n for n, _ in before]

        if not expected_names:
            print("\n[ERROR] Nenhuma linha encontrada. Abortando.")
            return

        print(f"\n[INFO] Ready antes: {sorted(ready_before)}")
        print(f"[INFO] Error/Processing antes (serao deletados): {sorted(to_delete_before)}")

        # --- Execucao REAL ---
        payload["files"] = [{"file_name": n} for n in expected_names]
        payload["workspace_name"] = str(page.url).split("/")[-1] or "workspace-realrun-test"

        print("\n[INFO] >>> EXECUCAO REAL (dry_run=False). Deletes serao efetuados. <<<\n")
        statuses, outcomes, ready_confirmed = _stream_read_and_delete(
            page,
            expected_names,
            payload,
            payload["workspace_name"],
            _log,
            should_continue=None,
            dry_run=False,
        )

        print("\n" + "=" * 72)
        print("RESULTADO EXECUCAO REAL")
        print("=" * 72)
        print("\nOutcomes:")
        print(f"  deleted:        {outcomes.get(DELETE_DELETED, [])}")
        print(f"  would_delete:   {outcomes.get(DELETE_WOULD_DELETE, [])}")
        print(f"  skipped_ready:  {outcomes.get(DELETE_SKIPPED_READY, [])}")
        print(f"  skipped_status: {outcomes.get(DELETE_SKIPPED_STATUS, [])}")
        print(f"  absent:         {outcomes.get(DELETE_ABSENT, [])}")
        print(f"  ambiguous:      {outcomes.get(DELETE_AMBIGUOUS, [])}")
        print(f"  delete_failed:  {outcomes.get(DELETE_FAILED, [])}")
        print(f"\nready_confirmed: {sorted(ready_confirmed)}")

        # --- Verificacao FINAL: reabre e confere a tabela ---
        print("\n[INFO] Verificacao final: reabrindo a tabela...")
        f5_reopen_files(page, payload, payload["workspace_name"], _log, None)
        after = _collect_rows(page)
        names_after = {n for n, _ in after}
        ready_after = {n for n, s in after if s == "Ready"}
        print("\n[INFO] Estado DEPOIS do teste:")
        for name, status in after:
            print(f"  '{name}' | status='{status}'")

        print("\n" + "=" * 72)
        print("VERIFICACAO DE INTEGRIDADE")
        print("=" * 72)

        # 1) Nenhum Ready pode ter sido deletado.
        lost_ready = sorted(n for n in ready_before if n not in names_after)
        if lost_ready:
            print(f"[FAIL] Arquivos Ready DESAPARECERAM (deletados por engano!): {lost_ready}")
        else:
            print("[PASS] Nenhum arquivo Ready foi deletado (todos os Ready continuam presentes).")

        # 2) Os Error/Processing deletados devem ter sumido.
        deleted = set(outcomes.get(DELETE_DELETED, []))
        still_present = sorted(n for n in deleted if n in names_after)
        if still_present:
            print(f"[WARN] Marcados como deletados mas ainda presentes: {still_present}")
        else:
            if deleted:
                print(f"[PASS] Arquivos Error/Processing deletados sumiram da tabela: {sorted(deleted)}")
            else:
                print("[INFO] Nenhum arquivo foi deletado nesta execucao.")

        print("\n[INFO] Teste REAL concluido.")

    finally:
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\nPressione ENTER para fechar o navegador...")
        except Exception:
            pass
        browser.close()
        print("[INFO] Navegador fechado.")


if __name__ == "__main__":
    main()
