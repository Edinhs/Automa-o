r"""
dryrun_monitor_rowbyrow.py -- Validacao DRY-RUN do monitor linha a linha.

Abre o workspace alvo com o perfil persistente do usuario 1, le todas as linhas
via _stream_read_and_delete com dry_run=True e confirma:
  - Linhas Ready  -> logadas como "Status linha a linha: <nome> = Ready"
  - Linhas Error/Processing -> logadas como "[DRY-RUN] Deletaria: <nome>" SEM clicar.
  - Nenhum delete real e efetuado.

Uso (a partir do diretorio backend/):
    .venv\Scripts\python.exe scripts\dryrun_monitor_rowbyrow.py

Variaveis de ambiente opcionais:
    INSPECT_USER_ID         (padrao 1)
    INSPECT_WORKSPACE_URL   (padrao: workspace de teste)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# PYTHONPATH e PLAYWRIGHT_BROWSERS_PATH
# ---------------------------------------------------------------------------
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

# Carrega .env se existir
_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_env_file))
        print(f"[INFO] .env carregado de {_env_file}")
    except ImportError:
        print("[WARN] python-dotenv nao instalado; .env nao carregado.")

# ---------------------------------------------------------------------------
# Imports do projeto
# ---------------------------------------------------------------------------
from app.services.playwright.browser import open_persistent_chromium  # noqa: E402
from app.services.playwright.playground_login import is_logged_in  # noqa: E402
from app.services.playwright.playground_workspace import wait_for_workspace_area  # noqa: E402
from app.services.playwright.playground_monitor import (  # noqa: E402
    open_files_tab,
    iter_page_file_rows,
    _match_row_to_expected,
    _stream_read_and_delete,
    f5_reopen_files,
    goto_next_files_page,
    read_all_pages_statuses,
    wait_for_files_table_stable,
)

# ---------------------------------------------------------------------------
# Parametros
# ---------------------------------------------------------------------------
USER_ID = int(os.environ.get("INSPECT_USER_ID", "1"))
WORKSPACE_URL = os.environ.get(
    "INSPECT_WORKSPACE_URL",
    "https://genai.stellantis.com/rag/workspaces/a6d5542d-2709-4a3e-84cf-da06be2e40a7",
)

# ---------------------------------------------------------------------------
# Logger simples
# ---------------------------------------------------------------------------
_log_lines: list[str] = []


def _log(level: str, message: str, **_kw) -> None:
    line = f"[{level.upper()}] {message}"
    print(line)
    _log_lines.append(line)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print(f"\n[INFO] Abrindo Chromium persistente para user_id={USER_ID}")
    browser = open_persistent_chromium(USER_ID)
    page = browser.page

    payload = {
        "workspace_playground_url": WORKSPACE_URL,
        "url": "https://genai.stellantis.com/",
        "workspace_name": "workspace-dryrun-test",
        "files": [],
        "manual_login_timeout_minutes": int(os.environ.get("INSPECT_LOGIN_MIN", "4")),
    }

    try:
        print(f"[INFO] Navegando para: {WORKSPACE_URL}")
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        if not is_logged_in(page):
            print("\n[WARN] Sessao NAO esta logada. Login manual necessario antes desta validacao.")
            print(f"[WARN] URL atual: {page.url}")
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

        # --- Passo 1: coleta nomes reais das linhas presentes na pagina 1 ---
        # Aguarda a tabela ESTABILIZAR antes de coletar: o Cloudscape renderiza linhas de
        # forma incremental apos F5/abertura — sem esta espera a coleta pode capturar apenas
        # as primeiras linhas renderizadas e perder arquivos como PRESENT SIMPLES HOMEWORK.docx.
        print("\n[INFO] Aguardando a tabela estabilizar antes de coletar nomes (rendering incremental)...")
        wait_for_files_table_stable(page, should_continue=None, timeout_seconds=15)
        print("[INFO] Coletando nomes reais das linhas para usar como expected_names...")
        real_names: list[str] = []
        for _row, row_name, row_status in iter_page_file_rows(page):
            if row_name:
                real_names.append(row_name)
                print(f"  Linha encontrada: '{row_name}' | status='{row_status}'")
        # Avanca para paginas seguintes se existirem (ate 5 paginas para nao demorar)
        for _pg in range(4):
            if not goto_next_files_page(page):
                break
            # Aguarda estabilizacao tambem nas paginas extras
            wait_for_files_table_stable(page, should_continue=None, timeout_seconds=10)
            for _row, row_name, row_status in iter_page_file_rows(page):
                if row_name and row_name not in real_names:
                    real_names.append(row_name)
                    print(f"  Linha (pag. extra): '{row_name}' | status='{row_status}'")

        if not real_names:
            print("\n[ERROR] Nenhuma linha encontrada na tabela. Workspace vazio ou aba Files nao carregou.")
            return

        print(f"\n[INFO] Total de arquivos encontrados: {len(real_names)}")
        print(f"[INFO] Nomes: {real_names}")

        # --- Passo 2: chama _stream_read_and_delete com DRY-RUN ---
        payload["files"] = [{"file_name": n} for n in real_names]
        payload["workspace_name"] = str(page.url).split("/")[-1] or "workspace-dryrun-test"

        print("\n[INFO] Iniciando _stream_read_and_delete com dry_run=True...")
        print("[INFO] Nenhum delete real sera efetuado.\n")

        statuses, outcomes, ready_confirmed = _stream_read_and_delete(
            page,
            real_names,
            payload,
            payload["workspace_name"],
            _log,
            should_continue=None,
            dry_run=True,
        )

        # --- Passo 3: relatorio ---
        print("\n" + "=" * 72)
        print("RESULTADO DRY-RUN")
        print("=" * 72)

        from app.services.playwright.playground_monitor import (
            DELETE_DELETED, DELETE_WOULD_DELETE, DELETE_SKIPPED_READY,
            DELETE_SKIPPED_STATUS, DELETE_ABSENT, DELETE_AMBIGUOUS, DELETE_FAILED,
        )

        print(f"\nStatuses por arquivo:")
        for name, data in statuses.items():
            print(f"  '{name}' -> {data.get('status')}")

        print(f"\nReady confirmados (ready_confirmed): {sorted(ready_confirmed)}")

        print(f"\nOutcomes:")
        print(f"  deleted:        {outcomes.get(DELETE_DELETED, [])}")
        print(f"  would_delete:   {outcomes.get(DELETE_WOULD_DELETE, [])}")
        print(f"  skipped_ready:  {outcomes.get(DELETE_SKIPPED_READY, [])}")
        print(f"  skipped_status: {outcomes.get(DELETE_SKIPPED_STATUS, [])}")
        print(f"  absent:         {outcomes.get(DELETE_ABSENT, [])}")
        print(f"  ambiguous:      {outcomes.get(DELETE_AMBIGUOUS, [])}")
        print(f"  delete_failed:  {outcomes.get(DELETE_FAILED, [])}")

        # Verifica invariante: deleted deve estar VAZIO em dry-run
        if outcomes.get(DELETE_DELETED):
            print(f"\n[FAIL] INVARIANTE VIOLADA: dry_run=True mas DELETE_DELETED nao esta vazio: {outcomes[DELETE_DELETED]}")
        else:
            print("\n[PASS] Invariante: nenhum delete real efetuado (DELETE_DELETED vazio).")

        # Verifica que every expected name foi classificado
        unclassified = [n for n in real_names if statuses.get(n, {}).get("status") == "NotFound"]
        if unclassified:
            print(f"\n[WARN] Arquivos que ficaram NotFound (nao vistos na passagem): {unclassified}")
        else:
            print("[PASS] Todos os arquivos foram classificados (nenhum NotFound).")

        print("\n[INFO] Validacao DRY-RUN concluida. Nenhuma acao destrutiva foi executada.")

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
