"""
inspect_teams_ui.py
====================
Abre o Teams Web com a sessao salva e captura um screenshot + HTML
para identificar os seletores corretos da interface atual.

Uso:
  cd backend
  .venv\\Scripts\\python.exe scripts\\inspect_teams_ui.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

TEAMS_URL = "https://teams.microsoft.com/v2/"
SESSION_DIR = Path(__file__).resolve().parents[1] / "data" / "browser_session_teams"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "teams_inspect"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    print("Abrindo Teams Web para inspecao de seletores...")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(TEAMS_URL, wait_until="domcontentloaded")
        print("Aguardando carregamento (15s)...")
        time.sleep(15)

        # Captura screenshot e HTML da pagina principal
        ss_path = OUT_DIR / "teams_home.png"
        html_path = OUT_DIR / "teams_home.html"
        page.screenshot(path=str(ss_path), full_page=False)
        html_path.write_text(page.content(), encoding="utf-8")
        print(f"Screenshot: {ss_path}")
        print(f"HTML:       {html_path}")

        # Tenta clicar no icone de Chat para garantir que estamos na aba certa
        chat_icons = [
            '[data-tid="chat-button"]',
            'a[href*="chat"]',
            'button[title*="Chat"]',
            'li[data-tid*="chat"]',
        ]
        for sel in chat_icons:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(timeout=3000)
                    print(f"  Clicou no icone de Chat: {sel}")
                    time.sleep(3)
                    break
            except Exception:
                continue

        # Captura depois de navegar para Chat
        ss2 = OUT_DIR / "teams_chat_view.png"
        html2 = OUT_DIR / "teams_chat_view.html"
        page.screenshot(path=str(ss2), full_page=False)
        html2.write_text(page.content(), encoding="utf-8")
        print(f"Screenshot (chat): {ss2}")

        # Proba seletores de busca candidatos
        print("\n--- Sondagem de seletores de busca ---")
        candidates = [
            'input[placeholder*="Search"]',
            'input[placeholder*="search"]',
            'input[placeholder*="Find"]',
            'input[placeholder*="Pesquisar"]',
            'input[type="search"]',
            'input[data-tid="search-input"]',
            'div[data-tid="search-box"] input',
            '[aria-label*="Search"] input',
            '[aria-label*="search"] input',
            '[aria-label*="Buscar"] input',
            'input[class*="search"]',
            'button[data-tid*="new-chat"]',
            '[data-tid="new-chat-button"]',
        ]
        found = []
        for sel in candidates:
            try:
                loc = page.locator(sel)
                cnt = loc.count()
                if cnt > 0:
                    try:
                        visible = loc.first.is_visible()
                    except Exception:
                        visible = "?"
                    print(f"  [ENCONTRADO] {sel!r}  count={cnt}  visible={visible}")
                    found.append(sel)
            except Exception as e:
                pass

        if not found:
            print("  Nenhum seletor de busca encontrado. Veja o HTML capturado.")

        print("\n--- Sondagem de seletores de novo chat ---")
        new_chat = [
            'button[data-tid*="new-chat"]',
            '[aria-label*="New chat"]',
            '[aria-label*="Novo chat"]',
            'button[title*="New chat"]',
        ]
        for sel in new_chat:
            try:
                loc = page.locator(sel)
                cnt = loc.count()
                if cnt > 0:
                    print(f"  [ENCONTRADO] {sel!r}  count={cnt}")
            except Exception:
                pass

        input("\nPressione ENTER para fechar...")
        ctx.close()
    print("Inspecao concluida.")


if __name__ == "__main__":
    main()
