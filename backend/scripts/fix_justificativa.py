import sys, time
sys.path.insert(0, '.')
from app.core.config import runtime_path
from app.services.playwright.browser import open_persistent_chromium

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
    shot(page, f"pa3t_{tag}_search.png")
    page.get_by_text(expect_token, exact=True).first.click(timeout=8000)
    time.sleep(1)

b = open_persistent_chromium(user_id=1, headless=False, session_dir=runtime_path('TEAMS_BROWSER_SESSION_PATH'))
page = b.page
try:
    page.goto('https://make.powerautomate.com/environments/Default-d852d5cd-724c-4128-8812-ffa5db3f8507/flows', wait_until='domcontentloaded', timeout=45000)
    time.sleep(6)
    page.get_by_text("Solicitar acesso - Teams", exact=False).first.click(timeout=15000)
    time.sleep(6)
    page.locator("button:has-text('Edit'), a:has-text('Edit')").first.click(timeout=15000)
    time.sleep(6)
    page.get_by_text("Create item", exact=True).first.click(timeout=15000)
    time.sleep(3)

    def show_all():
        page.get_by_text("Show all", exact=True).first.click(timeout=10000)
        time.sleep(2)
        shot(page, "pa3t_00_showall.png")

    safe("show all fields", show_all)

    # rola o painel de parametros para baixo para revelar Justificativa
    page.mouse.move(300, 500)
    page.mouse.wheel(0, 500)
    time.sleep(1)
    shot(page, "pa3t_00b_scrolled.png")

    safe("fill Justificativa", lambda: fill_dynamic(page, "Justificativa", "justificativa", "body/data/justificativa", "justificativa"))

    shot(page, "pa3t_01_before_save.png")

    def save_flow():
        page.get_by_text("Save", exact=True).first.click(timeout=10000)
        time.sleep(8)
        shot(page, "pa3t_02_after_save.png")

    safe("Save flow", save_flow)
finally:
    b.close()
