"""
setup_teams_session.py
======================
Script de uso ÚNICO para autenticar manualmente no Teams Web e salvar a sessão
persistente do Chromium. Após rodar este script e fazer login, todas as entregas
futuras serão feitas de forma silenciosa (headless).

Como usar:
  cd backend
  .venv\\Scripts\\python.exe scripts\\setup_teams_session.py
"""
import sys
import time
from pathlib import Path

# Garante que o módulo app é encontrado quando rodando direto
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

TEAMS_URL = "https://teams.microsoft.com/v2/"
SESSION_DIR = Path(__file__).resolve().parents[1] / "data" / "browser_session_teams"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

TIMEOUT_MIN = 10  # Minutos máximos para aguardar login


def is_logged_in(page) -> bool:
    url = (page.url or "").lower()
    if any(m in url for m in ["login.microsoftonline.com", "signin", "login.live.com"]):
        return False
    try:
        if page.locator(
            'input[placeholder*="Pesquisar"], input[placeholder*="Search"], '
            'input[data-tid="search-input"]'
        ).count() > 0:
            return True
        if page.locator('[data-tid="chat-list"], .chat-list, #chat-list').count() > 0:
            return True
    except Exception:
        pass
    return False


def main():
    print("=" * 60)
    print("  SETUP DA SESSAO DO TEAMS WEB -- Automation HUB")
    print("=" * 60)
    print(f"\n[DIR] Sessao sera salva em:\n   {SESSION_DIR}\n")
    print("[>]  Uma janela do Chrome vai abrir. Faca login com seu SSO")
    print("     corporativo. Apos detectar o login, a sessao e salva")
    print(f"     automaticamente. Voce tem {TIMEOUT_MIN} minutos.\n")
    input("   Pressione ENTER para abrir o Chrome...")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(TEAMS_URL, wait_until="domcontentloaded")

        print("\n[...] Aguardando login no Teams Web...")
        deadline = time.monotonic() + TIMEOUT_MIN * 60
        logged = False
        while time.monotonic() < deadline:
            try:
                if is_logged_in(page):
                    logged = True
                    break
            except Exception:
                pass
            time.sleep(2)

        if logged:
            print("\n[OK] Login detectado com sucesso!")
            print("     Aguardando 5s para estabilizar a sessao...")
            time.sleep(5)
            context.close()
            print("\n[PRONTO] Sessao salva! O agente de entrega do Teams agora")
            print("         funciona em modo headless sem login manual.")
        else:
            context.close()
            print("\n[ERRO] Timeout -- login nao detectado em", TIMEOUT_MIN, "minutos.")
            print("       Tente novamente ou verifique as credenciais SSO.")
            sys.exit(1)


if __name__ == "__main__":
    main()
