import sys, time
sys.path.insert(0, '.')
from app.core.config import runtime_path
from app.services.playwright.browser import open_persistent_chromium

HTML_MESSAGE = (
    "<p><b>Nova solicitação de acesso</b></p>"
    "<ul>"
    "<li><b>Solicitante:</b> @{outputs('Post_adaptive_card_and_wait_for_a_response')?['body/responder']?['displayName']} "
    "(@{outputs('Post_adaptive_card_and_wait_for_a_response')?['body/responder']?['email']})</li>"
    "<li><b>ID de rede:</b> @{outputs('Post_adaptive_card_and_wait_for_a_response')?['body/data']?['idrede']}</li>"
    "<li><b>SPEC / Workspace:</b> @{outputs('Post_adaptive_card_and_wait_for_a_response')?['body/data']?['spec']}</li>"
    "<li><b>Justificativa:</b> @{outputs('Post_adaptive_card_and_wait_for_a_response')?['body/data']?['justificativa']}</li>"
    "</ul>"
    "<p><a href=\"https://teams.microsoft.com/l/chat/0/0?users=@{outputs('Post_adaptive_card_and_wait_for_a_response')?['body/responder']?['email']}\">Abrir chat com o solicitante</a></p>"
)

def shot(page, name):
    path = f"data/screenshots/{name}"
    page.screenshot(path=path, full_page=False)
    print(f"Screenshot: {path}")

def safe(label, fn):
    try:
        fn()
        print(f"[OK] {label}")
        return True
    except Exception as e:
        print(f"[FAIL] {label}: {e}")
        return False

b = open_persistent_chromium(user_id=1, headless=False, session_dir=runtime_path('TEAMS_BROWSER_SESSION_PATH'))
page = b.page
try:
    page.goto('https://make.powerautomate.com/environments/Default-d852d5cd-724c-4128-8812-ffa5db3f8507/flows', wait_until='domcontentloaded', timeout=45000)
    time.sleep(6)
    page.get_by_text("Solicitar acesso - Teams", exact=False).first.click(timeout=15000)
    time.sleep(6)
    page.locator("button:has-text('Edit'), a:has-text('Edit')").first.click(timeout=15000)
    time.sleep(6)
    shot(page, "pa3w_00_reopen.png")

    def recover():
        page.get_by_text("Recover flow", exact=False).first.click(timeout=8000)
        time.sleep(4)

    safe("recover unsaved draft", recover)

    page.get_by_text("Post message in a chat or channel", exact=True).first.click(timeout=15000)
    time.sleep(3)
    shot(page, "pa3w_01_panel.png")

    def config_message():
        # o icone </> fica na barra de ferramentas do editor "Mensagem"
        code_icon = page.locator("svg", has_text="").locator("..").filter(has_text="")  # placeholder unused
        page.mouse.click(578, 514)
        time.sleep(1)
        shot(page, "pa3w_02_after_code_click.png")
        # o campo ja esta em modo codigo - clica na area de texto e substitui o conteudo
        page.mouse.click(200, 550)
        time.sleep(0.5)
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        time.sleep(0.5)
        page.keyboard.type(HTML_MESSAGE, delay=2)
        time.sleep(1.5)
        shot(page, "pa3w_03_message_typed.png")

    safe("configure Message (HTML)", config_message)

    def save_flow():
        page.get_by_text("Save", exact=True).first.click(timeout=10000)
        time.sleep(8)
        shot(page, "pa3w_04_after_save.png")

    safe("Save flow", save_flow)
finally:
    b.close()
