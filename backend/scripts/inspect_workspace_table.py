r"""
Inspect Workspace Table - READ-ONLY DOM dump for selector mapping.

Abre o workspace de teste, navega para a aba Files e faz dump das estruturas
da tabela (cabecalhos, primeiras linhas, celulas de Status, controles de Delete,
paginacao) SEM clicar em nenhum controle destrutivo.

Uso:
    cd backend
    .venv\Scripts\python.exe scripts\inspect_workspace_table.py

Se a sessao do Chromium nao estiver logada, uma janela visivel abre e o script
AGUARDA voce concluir o login (SSO) manualmente — entao faz o dump automaticamente.

Variaveis relevantes:
    INSPECT_USER_ID        - user_id do contexto persistente (default 1 = admin local)
    INSPECT_WORKSPACE_URL  - URL direta do workspace a inspecionar
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Ajusta o PYTHONPATH para importar app.*
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Configura PLAYWRIGHT_BROWSERS_PATH para o Chromium offline, igual ao start_agent.bat
_ms_playwright = BACKEND_DIR / "ms-playwright"
if _ms_playwright.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_ms_playwright))
    print(f"[INFO] PLAYWRIGHT_BROWSERS_PATH={os.environ['PLAYWRIGHT_BROWSERS_PATH']}")

# Carrega o .env do backend antes de importar settings
_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(str(_env_file))
    print(f"[INFO] Carregado .env de {_env_file}")

# Agora importa os modulos do projeto
from app.services.playwright.browser import open_persistent_chromium  # noqa: E402
from app.services.playwright.playground_login import ensure_logged_in, is_logged_in  # noqa: E402
from app.services.playwright.playground_workspace import wait_for_workspace_area  # noqa: E402
from app.services.playwright.playground_monitor import open_files_tab as project_open_files_tab  # noqa: E402


def _log(level: str, message: str, **_kw) -> None:
    """Log compativel com a assinatura usada pelos helpers do projeto (level, msg, **kw)."""
    print(f"[{level.upper()}] {message}")


def _rows_present(page) -> bool:
    """True se ha linhas de tabela renderizadas (table tbody tr ou role=row)."""
    try:
        if page.locator("table tbody tr").count() > 0:
            return True
        return page.locator("[role='row']").count() > 0
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Parametros
# ---------------------------------------------------------------------------
USER_ID = int(os.environ.get("INSPECT_USER_ID", "1"))
WORKSPACE_URL = os.environ.get(
    "INSPECT_WORKSPACE_URL",
    "https://genai.stellantis.com/rag/workspaces/a6d5542d-2709-4a3e-84cf-da06be2e40a7",
)
FILES_TAB_CANDIDATES = ["Files", "Arquivos", "Status"]
MAX_ROWS_DUMP = 8   # maximas linhas de corpo para dump de outerHTML


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def dump_table_dom(page) -> dict:
    """Extrai, via JS, tudo que precisamos para mapear os seletores."""
    return page.evaluate(
        """
        () => {
          const clean = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
          const attrOf = (el, ...attrs) => {
            for (const a of attrs) {
              const v = el && el.getAttribute && el.getAttribute(a);
              if (v) return clean(v);
            }
            return '';
          };
          const textOf = (el) => {
            if (!el) return '';
            return clean([
              el.innerText || el.textContent || '',
              attrOf(el, 'aria-label', 'title'),
            ].filter(Boolean).join(' | '));
          };

          const result = {
            tables: [],
            role_rows: [],
            pagination_buttons: [],
            all_delete_buttons: [],
          };

          // --- Tabelas <table> ---
          document.querySelectorAll('table').forEach((table, ti) => {
            const headers = Array.from(
              table.querySelectorAll('thead th, thead [role="columnheader"], tr:first-child th')
            ).map((h) => ({
              text: textOf(h),
              class: clean(h.className || ''),
              outerHTML: h.outerHTML.slice(0, 300),
            }));

            const rows = [];
            table.querySelectorAll('tbody tr').forEach((row, ri) => {
              if (ri >= """ + str(MAX_ROWS_DUMP) + """) return;
              const cells = Array.from(
                row.querySelectorAll('td, th, [role="cell"], [role="gridcell"]')
              ).map((td) => {
                // Encontra todos os botoes dentro desta celula (para mapear o delete)
                const buttons = Array.from(td.querySelectorAll('button, [role="button"], a[role="button"]')).map((b) => ({
                  text: textOf(b),
                  ariaLabel: attrOf(b, 'aria-label'),
                  title: attrOf(b, 'title'),
                  class: clean(b.className || '').slice(0, 200),
                  disabled: b.disabled || b.getAttribute('disabled') !== null,
                  innerText: clean(b.innerText || b.textContent || ''),
                  outerHTML: b.outerHTML.slice(0, 400),
                }));
                // Icones SVG/IMG dentro da celula
                const icons = Array.from(td.querySelectorAll('[class*="icon"], svg, img')).slice(0, 5).map((ic) => ({
                  tag: ic.tagName,
                  class: clean(ic.className || '').slice(0, 200),
                  ariaLabel: attrOf(ic, 'aria-label'),
                  title: attrOf(ic, 'title'),
                }));
                return {
                  text: textOf(td),
                  innerText: clean(td.innerText || td.textContent || ''),
                  ariaLabel: attrOf(td, 'aria-label'),
                  class: clean(td.className || '').slice(0, 150),
                  buttons,
                  icons,
                };
              });
              // outerHTML resumido da linha inteira
              const rowHTML = row.outerHTML.slice(0, 2000);
              rows.push({ index: ri, cells, rowHTML });
            });

            result.tables.push({ tableIndex: ti, headers, rows });
          });

          // --- role=row fora de <table> ---
          document.querySelectorAll('[role="row"]').forEach((row, ri) => {
            if (row.closest('table')) return;
            if (ri >= """ + str(MAX_ROWS_DUMP) + """) return;
            const cells = Array.from(
              row.querySelectorAll('[role="cell"], [role="gridcell"], td, th')
            ).map((td) => ({
              text: textOf(td),
              ariaLabel: attrOf(td, 'aria-label'),
              class: clean(td.className || '').slice(0, 150),
            }));
            result.role_rows.push({ index: ri, text: textOf(row), cells });
          });

          // --- Botoes de paginacao ---
          document.querySelectorAll(
            'button[class*="awsui_arrow"], [class*="awsui_pagination"] button, [aria-label*="next" i], [aria-label*="proxim" i]'
          ).forEach((b) => {
            result.pagination_buttons.push({
              text: textOf(b),
              ariaLabel: attrOf(b, 'aria-label'),
              title: attrOf(b, 'title'),
              class: clean(b.className || '').slice(0, 250),
              disabled: b.disabled || b.getAttribute('disabled') !== null,
              outerHTML: b.outerHTML.slice(0, 400),
            });
          });

          // --- Todos os botoes com Delete/Excluir (pagina inteira) ---
          document.querySelectorAll('button, [role="button"]').forEach((b) => {
            const txt = textOf(b).toLowerCase();
            if (txt.includes('delete') || txt.includes('excluir') || txt.includes('remove') || txt.includes('remover')) {
              result.all_delete_buttons.push({
                text: textOf(b),
                ariaLabel: attrOf(b, 'aria-label'),
                title: attrOf(b, 'title'),
                class: clean(b.className || '').slice(0, 250),
                disabled: b.disabled || b.getAttribute('disabled') !== null,
                outerHTML: b.outerHTML.slice(0, 500),
              });
            }
          });

          return result;
        }
        """
    )


def open_files_tab(page) -> bool:
    for text in FILES_TAB_CANDIDATES:
        for loc in [
            page.get_by_role("tab", name=text),
            page.get_by_role("button", name=text),
            page.get_by_text(text, exact=True),
        ]:
            try:
                if loc.count() and loc.first.is_visible(timeout=3000):
                    loc.first.click(timeout=5000)
                    time.sleep(1.5)
                    print(f"[INFO] Aba Files aberta via texto '{text}'")
                    return True
            except Exception:
                continue
    print("[WARN] Nao foi possivel clicar na aba Files; continuando com o estado atual.")
    return False


def main():
    print(f"[INFO] Abrindo contexto persistente para user_id={USER_ID}")
    browser = open_persistent_chromium(USER_ID)
    page = browser.page
    payload = {
        "workspace_playground_url": WORKSPACE_URL,
        "url": "https://genai.stellantis.com/",
        # Janela para concluir o SSO manual na janela visivel (min). Ajuste via INSPECT_LOGIN_MIN.
        "manual_login_timeout_minutes": int(os.environ.get("INSPECT_LOGIN_MIN", "4")),
    }
    try:
        print(f"[INFO] Navegando para: {WORKSPACE_URL}")
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        # Login robusto: se nao estiver logado, AGUARDA o SSO manual (ate MANUAL_LOGIN_TIMEOUT_MINUTES)
        # usando o mesmo fluxo do projeto, em vez de um sleep fixo curto.
        if not is_logged_in(page):
            print("[WARN] Sessao NAO logada. Conclua o login (SSO) na JANELA do Chromium que abriu.")
            print("[INFO] Aguardando login manual... (a janela e visivel; faca o SSO normalmente)")
            ensure_logged_in(page, payload, _log)
        else:
            print("[INFO] Sessao ja logada.")

        # Apos o login o SSO pode ter redirecionado; re-navega para o workspace alvo.
        print(f"[INFO] Re-navegando para o workspace: {WORKSPACE_URL}")
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        # SPA React: 'domcontentloaded' retorna antes da tabela renderizar. Espera networkidle.
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        try:
            wait_for_workspace_area(page, "files", timeout_ms=20000)
        except Exception:
            pass

        # Abre a aba Files e ESPERA as linhas renderizarem (lazy). Faz polling: a area de
        # arquivos pode ja estar visivel sem aba separada, ou a aba aparece com atraso.
        print("[INFO] Abrindo aba Files e aguardando a tabela renderizar...")
        deadline = time.time() + 45
        while time.time() < deadline:
            try:
                project_open_files_tab(page, _log)
            except Exception:
                try:
                    open_files_tab(page)
                except Exception:
                    pass
            if _rows_present(page):
                break
            time.sleep(2)
        # Garante um tempo final para a virtualizacao/Ajax assentar.
        rows_deadline = time.time() + 25
        while time.time() < rows_deadline and not _rows_present(page):
            time.sleep(1.5)

        # Diagnostico do estado da pagina (ajuda quando o dump sai vazio).
        try:
            n_table = page.locator("table").count()
            n_tr = page.locator("table tbody tr").count()
            n_role = page.locator("[role='row']").count()
            print(f"[DIAG] URL atual: {page.url}")
            print(f"[DIAG] <table>={n_table}  table tbody tr={n_tr}  [role=row]={n_role}")
            body = page.locator("body").inner_text(timeout=4000)
            snippet = " ".join(body.split())[:500]
            print(f"[DIAG] body (500 chars): {snippet}")
        except Exception as exc:
            print(f"[DIAG] falha ao coletar diagnostico: {exc}")

        print("[INFO] Extraindo DOM da tabela...")
        dom_data = dump_table_dom(page)

        # --- Imprime resultado estruturado ---
        print("\n" + "=" * 70)
        print("DUMP DO DOM DA TABELA DE ARQUIVOS (READ-ONLY)")
        print("=" * 70)

        for ti, table in enumerate(dom_data.get("tables", [])):
            print(f"\n--- TABELA {ti} ---")
            headers = table.get("headers", [])
            print(f"  Cabecalhos ({len(headers)}):")
            for i, h in enumerate(headers):
                print(f"    [{i}] text='{h['text']}' class='{h['class'][:80]}'")

            rows = table.get("rows", [])
            print(f"  Linhas de corpo ({len(rows)} exibidas):")
            for row in rows:
                print(f"\n  Linha {row['index']}:")
                for ci, cell in enumerate(row["cells"]):
                    print(f"    Celula [{ci}]: text='{cell['text'][:100]}' ariaLabel='{cell['ariaLabel']}'")
                    for btn in cell.get("buttons", []):
                        print(f"      BUTTON: text='{btn['text'][:80]}' aria-label='{btn['ariaLabel']}' title='{btn['title']}' disabled={btn['disabled']}")
                        print(f"        class='{btn['class'][:100]}'")
                    for ic in cell.get("icons", []):
                        print(f"      ICON <{ic['tag']}>: class='{ic['class'][:80]}' aria-label='{ic['ariaLabel']}' title='{ic['title']}'")
                print(f"    outerHTML (truncado): {row['rowHTML'][:600]}")

        print("\n--- role=row (fora de <table>) ---")
        for rr in dom_data.get("role_rows", []):
            print(f"  [{rr['index']}] text='{rr['text'][:80]}' cells={[c['text'][:40] for c in rr.get('cells', [])]}")

        print("\n--- BOTOES DE PAGINACAO ---")
        for pb in dom_data.get("pagination_buttons", []):
            print(f"  text='{pb['text']}' aria-label='{pb['ariaLabel']}' disabled={pb['disabled']}")
            print(f"    class='{pb['class'][:100]}'")
            print(f"    outerHTML: {pb['outerHTML'][:300]}")

        print("\n--- TODOS OS BOTOES DELETE/EXCLUIR/REMOVE NA PAGINA ---")
        for db in dom_data.get("all_delete_buttons", []):
            print(f"  text='{db['text'][:80]}' aria-label='{db['ariaLabel']}' title='{db['title']}' disabled={db['disabled']}")
            print(f"    class='{db['class'][:120]}'")
            print(f"    outerHTML: {db['outerHTML'][:400]}")

        # Salva JSON completo
        out_path = Path(__file__).parent / "workspace_table_dump.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(dom_data, f, ensure_ascii=False, indent=2)
        print(f"\n[INFO] Dump completo salvo em: {out_path}")
        print("[INFO] Inspecao concluida. NENHUMA acao destrutiva foi realizada.")

    finally:
        # So bloqueia esperando ENTER quando rodando interativamente (TTY). Em execucao
        # automatizada (stdin nao-interativo) fecha direto, sem travar.
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\nPressione ENTER para fechar o navegador...")
        except Exception:
            pass
        browser.close()


if __name__ == "__main__":
    main()
