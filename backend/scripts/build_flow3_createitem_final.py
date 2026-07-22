import sys, time
sys.path.insert(0, '.')
from app.core.config import runtime_path
from app.services.playwright.browser import open_persistent_chromium

SP_SITE = "https://shiftup.sharepoint.com/sites/StellantisAutomationHub"
SP_LIST = "Solicitações de Acesso a Workspace"

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

def fill_dynamic(page, label_text, search_term, expect_token, tag):
    label = page.get_by_text(label_text, exact=True).first
    box = label.bounding_box()
    page.mouse.click(box["x"] + 120, box["y"] + 32)
    time.sleep(0.8)
    page.keyboard.type("/", delay=50)
    time.sleep(1)
    page.get_by_text("Insert dynamic content", exact=True).first.click(timeout=5000)
    time.sleep(1.2)
    search = page.get_by_placeholder("Search", exact=True).first
    search.click(timeout=5000)
    search.fill(search_term)
    time.sleep(1.2)
    shot(page, f"pa3q_{tag}_search.png")
    page.get_by_text(expect_token, exact=True).first.click(timeout=8000)
    time.sleep(1)
    # fecha o flyout clicando fora
    page.mouse.click(300, 700)
    time.sleep(0.5)

def fill_literal(page, label_text, value, tag):
    label = page.get_by_text(label_text, exact=True).first
    box = label.bounding_box()
    page.mouse.click(box["x"] + 120, box["y"] + 32)
    time.sleep(0.8)
    page.keyboard.type(value, delay=20)
    time.sleep(0.8)
    shot(page, f"pa3q_{tag}_literal.png")

b = open_persistent_chromium(user_id=1, headless=False, session_dir=runtime_path('TEAMS_BROWSER_SESSION_PATH'))
page = b.page
try:
    page.goto('https://make.powerautomate.com/environments/Default-d852d5cd-724c-4128-8812-ffa5db3f8507/flows', wait_until='domcontentloaded', timeout=45000)
    time.sleep(6)
    page.get_by_text("Solicitar acesso - Teams", exact=False).first.click(timeout=15000)
    time.sleep(6)
    page.locator("button:has-text('Edit'), a:has-text('Edit')").first.click(timeout=15000)
    time.sleep(6)
    shot(page, "pa3q_00_designer.png")

    def add_create_item():
        page.mouse.click(639, 306)
        time.sleep(2)
        search_box = page.get_by_placeholder("Search for an action or connector")
        search_box.click(timeout=10000)
        search_box.fill("SharePoint Create item")
        time.sleep(3)
        page.get_by_text("Create item", exact=True).first.click(timeout=15000)
        time.sleep(5)

    safe("add Create item action", add_create_item)

    def config_site_list():
        site_box = page.locator("input[placeholder*='Site' i]").first
        site_box.click(timeout=10000)
        time.sleep(1)
        page.keyboard.type(SP_SITE, delay=10)
        time.sleep(3)
        page.get_by_text("StellantisAutomationHub", exact=False).first.click(timeout=10000)
        time.sleep(3)
        list_box = page.locator("input[placeholder*='List' i]").first
        list_box.click(timeout=10000)
        time.sleep(1)
        page.get_by_text(SP_LIST, exact=False).first.click(timeout=10000)
        time.sleep(3)

    safe("configure Site/List", config_site_list)

    def show_all():
        page.get_by_text("Show all", exact=True).first.click(timeout=10000)
        time.sleep(2)

    safe("show all fields", show_all)

    safe("fill Titulo <- spec", lambda: fill_dynamic(page, "Título", "spec", "body/data/spec", "titulo"))
    safe("fill Solicitante <- displayName", lambda: fill_dynamic(page, "Solicitante", "displayName", "body/responder/displayName", "solicitante"))
    safe("fill IDRede <- idrede", lambda: fill_dynamic(page, "IDRede", "idrede", "body/data/idrede", "idrede"))

    shot(page, "pa3q_after_first3.png")

    # rola para baixo para revelar Email, Justificativa e Status Value
    page.mouse.wheel(0, 400)
    time.sleep(1)
    shot(page, "pa3q_scrolled.png")

    safe("fill Email <- responder email", lambda: fill_dynamic(page, "Email", "email", "body/responder/email", "email"))
    safe("fill Justificativa <- justificativa", lambda: fill_dynamic(page, "Justificativa", "justificativa", "body/data/justificativa", "justificativa"))

    page.mouse.wheel(0, 400)
    time.sleep(1)
    shot(page, "pa3q_scrolled2.png")

    safe("fill Status Value = Pendente", lambda: fill_literal(page, "Status Value", "Pendente", "status"))

    shot(page, "pa3q_before_save.png")

    def save_flow():
        page.get_by_text("Save", exact=True).first.click(timeout=10000)
        time.sleep(8)
        shot(page, "pa3q_after_save.png")

    safe("Save flow", save_flow)
finally:
    b.close()
