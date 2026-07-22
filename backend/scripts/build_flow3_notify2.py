import sys, time
sys.path.insert(0, '.')
from app.core.config import runtime_path
from app.services.playwright.browser import open_persistent_chromium

APPROVER_EMAIL = "ederson.siqueiradossantos@stellantis.com"

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
    shot(page, "pa3v_00_reopen.png")

    def recover():
        page.get_by_text("Recover flow", exact=False).first.click(timeout=8000)
        time.sleep(4)
        shot(page, "pa3v_01_recovered.png")

    safe("recover unsaved draft", recover)

    page.get_by_text("Post message in a chat or channel", exact=True).first.click(timeout=15000)
    time.sleep(3)
    shot(page, "pa3v_02_panel.png")

    def config_postin():
        label = page.get_by_text("Post in", exact=False).first
        box = label.bounding_box()
        page.mouse.click(box["x"] + 120, box["y"] + 32)
        time.sleep(1)
        shot(page, "pa3v_03_postin_open.png")
        page.get_by_text("Conversar com o bot do Flow", exact=True).first.click(timeout=8000)
        time.sleep(1.5)
        shot(page, "pa3v_04_postin_selected.png")

    safe("configure Post in = Conversar com o bot do Flow", config_postin)

    def config_recipient():
        label = page.get_by_text("Recipient", exact=False).first
        box = label.bounding_box()
        page.mouse.click(box["x"] + 120, box["y"] + 32)
        time.sleep(1)
        page.keyboard.type(APPROVER_EMAIL, delay=15)
        time.sleep(1.5)
        shot(page, "pa3v_05_recipient.png")
        page.get_by_text("EDERSON SIQUEIRA DOS SANTOS", exact=False).first.click(timeout=8000)
        time.sleep(1.5)
        shot(page, "pa3v_05b_recipient_selected.png")

    safe("configure Recipient", config_recipient)

    def config_message():
        placeholder_field = page.get_by_placeholder("Adicionar mensagem", exact=False).first
        placeholder_field.click(timeout=8000)
        time.sleep(1)
        shot(page, "pa3v_06_message_area.png")
        code_btn = page.locator("button[title*='Code' i], button[aria-label*='Code' i]").first
        code_btn.click(timeout=8000)
        time.sleep(1)
        shot(page, "pa3v_07_message_codeview.png")
        page.keyboard.type(HTML_MESSAGE, delay=2)
        time.sleep(1.5)
        shot(page, "pa3v_08_message_typed.png")

    safe("configure Message (HTML)", config_message)

    def save_flow():
        page.get_by_text("Save", exact=True).first.click(timeout=10000)
        time.sleep(8)
        shot(page, "pa3v_09_after_save.png")

    safe("Save flow", save_flow)
finally:
    b.close()
