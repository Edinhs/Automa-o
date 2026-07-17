"""
verify_teams_session.py
=======================
Verifica se a sessao do Teams Web esta ativa, abrindo o Chrome
com a sessao salva e checando se o login ja aconteceu.

Como usar:
  cd backend
  .venv\\Scripts\\python.exe scripts\\verify_teams_session.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

TEAMS_URL = "https://teams.microsoft.com/v2/"
SESSION_DIR = Path(__file__).resolve().parents[1] / "data" / "browser_session_teams"


def is_logged_in(page) -> bool:
    """Deteccao robusta de login no Teams Web."""
    url = (page.url or "").lower()
    # Se estiver na pagina de login, nao esta logado
    if any(m in url for m in ["login.microsoftonline.com", "login.live.com", "signin"]):
        return False
    # Se URL contem teams.microsoft.com sem ser redirect de login, esta logado
    if "teams.microsoft.com" in url and "auth" not in url:
        # Verifica presenca de elementos da UI do Teams
        try:
            # Tenta varios seletores que indicam que o Teams carregou
            checks = [
                'input[placeholder*="Search"], input[placeholder*="Pesquisar"]',
                '[data-tid="chat-list"]',
                '[data-tid="app-layout"]',
                'div[aria-label="Chat"]',
                'div[aria-label="Teams"]',
                'nav[aria-label]',
                '#app-host',
                'div[class*="app-container"]',
            ]
            for sel in checks:
                try:
                    if page.locator(sel).count() > 0:
                        return True
                except Exception:
                    pass
            # Se URL e teams.microsoft.com e nao e login, assume logado
            if "teams.microsoft.com" in url:
                return True
        except Exception:
            pass
    return False


def main():
    print("=" * 60)
    print("  VERIFICACAO DA SESSAO DO TEAMS WEB")
    print("=" * 60)
    
    files = list(SESSION_DIR.rglob("*"))
    print(f"\n[DIR] Sessao em: {SESSION_DIR}")
    print(f"[INFO] Arquivos salvos: {len(files)}")

    if not files:
        print("\n[AVISO] Nenhum arquivo de sessao encontrado.")
        print("         Execute setup_teams_session.py primeiro.")
        sys.exit(1)

    print("\n[...] Abrindo Chrome com a sessao salva para verificar...")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(TEAMS_URL, wait_until="domcontentloaded")
        
        print("[...] Aguardando carregamento do Teams (20s)...")
        time.sleep(20)
        
        url_final = page.url
        print(f"[INFO] URL atual: {url_final}")
        
        logged = is_logged_in(page)
        
        if logged:
            print("\n[OK] SESSAO VALIDA! Teams detectado como logado.")
            print("     O agente de entrega funcionara em headless.")
        else:
            print("\n[ATENCAO] Teams nao detectado como logado.")
            print(f"           URL atual: {url_final}")
            print("           Se o Teams estiver visivel na tela, ignore este aviso.")
            print("           A deteccao pode falhar em versoes novas do Teams.")
        
        print("\nPressione ENTER para fechar o Chrome e salvar a sessao...")
        try:
            input()
        except EOFError:
            time.sleep(5)
        
        context.close()
        print("\n[PRONTO] Sessao preservada. Chrome fechado.")


if __name__ == "__main__":
    main()
