"""
inspect_teams_textbox.py
========================
Navega ate um chat do Teams e sonda os seletores do campo de mensagem.
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright

SESSION_DIR = Path(__file__).resolve().parents[1] / "data" / "browser_session_teams"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "teams_inspect"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CHAT_NAME = "1:1 Ederson"
TEAMS_URL = "https://teams.microsoft.com/v2/"

def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(TEAMS_URL, wait_until="domcontentloaded")
        time.sleep(12)

        # Clica no Chat na sidebar
        chat_icons = ['[data-tid="chat-button"]', 'a[href*="chat"]', 'button[title*="Chat"]']
        for sel in chat_icons:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(timeout=3000)
                    time.sleep(3)
                    break
            except Exception:
                pass

        # Tenta navegar ate o chat pelo nome na sidebar
        print(f"Procurando chat '{CHAT_NAME}' na sidebar...")
        found_chat = False
        for sel in [f'span:has-text("{CHAT_NAME}")', f'div:has-text("{CHAT_NAME}")']:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    for i in range(min(loc.count(), 8)):
                        item = loc.nth(i)
                        try:
                            if item.is_visible() and item.bounding_box():
                                item.click(timeout=3000)
                                found_chat = True
                                print(f"  Chat encontrado via: {sel} (idx {i})")
                                time.sleep(3)
                                break
                        except Exception:
                            continue
                if found_chat:
                    break
            except Exception:
                pass

        if not found_chat:
            print("  Chat nao encontrado na sidebar. Tentando busca...")
            search = page.locator('input[type="search"]')
            if search.count() > 0:
                search.first.click()
                time.sleep(1)
                search.first.type(CHAT_NAME, delay=80)
                time.sleep(3)
                for sel in ['[role="option"]', '[role="listitem"]', 'li']:
                    try:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            loc.first.click(timeout=3000)
                            print(f"  Chat selecionado via busca: {sel}")
                            time.sleep(3)
                            break
                    except Exception:
                        pass

        # Screenshot do estado do chat
        ss = OUT_DIR / "teams_chat_open.png"
        page.screenshot(path=str(ss))
        html = OUT_DIR / "teams_chat_open.html"
        html.write_text(page.content(), encoding="utf-8")
        print(f"Screenshot: {ss}")

        # Sonda seletores do textbox
        print("\n--- Seletores do campo de mensagem ---")
        candidates = [
            'div[contenteditable="true"]',
            'div[contenteditable]',
            'textarea',
            'div[role="textbox"]',
            '[data-tid="ckeditor-reply-textbox"]',
            'div[class*="ck-content"]',
            'div[class*="editor"]',
            '[aria-label*="mensagem"]',
            '[aria-label*="message"]',
            '[aria-label*="Digite"]',
            '[aria-label*="Type"]',
            '[aria-placeholder*="Digite"]',
            '[aria-placeholder*="Type"]',
            '[placeholder*="Digite"]',
        ]
        found = []
        for sel in candidates:
            try:
                loc = page.locator(sel)
                cnt = loc.count()
                if cnt > 0:
                    try:
                        vis = loc.first.is_visible()
                        bbox = loc.first.bounding_box()
                        aria = loc.first.get_attribute("aria-label") or ""
                        ph = loc.first.get_attribute("aria-placeholder") or ""
                        print(f"  [OK] {sel!r}  count={cnt}  visible={vis}  aria-label={aria!r}  placeholder={ph!r}")
                        found.append(sel)
                    except Exception as e:
                        print(f"  [OK] {sel!r}  count={cnt}  (detalhe: {e})")
                        found.append(sel)
            except Exception:
                pass

        if not found:
            print("  Nenhum seletor de textbox encontrado!")

        input("\nPressione ENTER para fechar...")
        ctx.close()

if __name__ == "__main__":
    main()
