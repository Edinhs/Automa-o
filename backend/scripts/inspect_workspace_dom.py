r"""
inspect_workspace_dom.py -- READ-ONLY live DOM inspection for hypothesis testing.

Hypothesis: the "deleting the first line" bug is caused by _truncation_match matching
the WRONG row when the Cloudscape table truncates long filenames with an ellipsis,
so two different files share the same visible prefix.

What this script reports (strictly no destructive actions):
  a) thead presence and header cell labels.
  b) First ~8 tbody rows: each cell's innerText, whether the Name cell ends with ellipsis
     (visually truncated), the Status cell text + any status aria-label/title, and the
     delete/actions control aria-label/title.
  c) Leading checkbox/select column? Any non-data tbody row?
  d) Any stable per-row identity attribute carrying the FULL untruncated filename
     (title, aria-label, data-testid, data-*, row id). THE MOST IMPORTANT FINDING.
  e) Pagination controls + page size.

Usage (from backend dir):
    .venv\Scripts\python.exe scripts\inspect_workspace_dom.py

Environment overrides:
    INSPECT_USER_ID          (default 1)
    INSPECT_WORKSPACE_URL    (default: hardcoded target workspace)
    PLAYWRIGHT_BROWSERS_PATH (auto-set to AppData ms-playwright if not set)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# PYTHONPATH: import app.* from backend/
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# ---------------------------------------------------------------------------
# PLAYWRIGHT_BROWSERS_PATH: prefer backend/ms-playwright, fall back to AppData
# ---------------------------------------------------------------------------
def _set_browsers_path() -> str:
    # 1) Already set by caller
    existing = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if existing and Path(existing).exists():
        print(f"[INFO] PLAYWRIGHT_BROWSERS_PATH already set: {existing}")
        return existing
    # 2) Project-local backend/ms-playwright
    local_msp = BACKEND_DIR / "ms-playwright"
    if local_msp.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_msp)
        print(f"[INFO] PLAYWRIGHT_BROWSERS_PATH -> {local_msp} (project-local)")
        return str(local_msp)
    # 3) AppData ms-playwright (dev machine where playwright is installed globally)
    appdata = Path(os.environ.get("LOCALAPPDATA", "C:/Users/Default/AppData/Local"))
    appdata_msp = appdata / "ms-playwright"
    if appdata_msp.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(appdata_msp)
        print(f"[INFO] PLAYWRIGHT_BROWSERS_PATH -> {appdata_msp} (AppData fallback)")
        return str(appdata_msp)
    print("[WARN] ms-playwright not found; Playwright will attempt online download.")
    return ""

_set_browsers_path()

# ---------------------------------------------------------------------------
# Load .env if present (picks up BROWSER_SESSION_PATH etc.)
# ---------------------------------------------------------------------------
_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_env_file))
        print(f"[INFO] Loaded .env from {_env_file}")
    except ImportError:
        print("[WARN] python-dotenv not installed; .env not loaded.")

# ---------------------------------------------------------------------------
# Project imports (after path and env setup)
# ---------------------------------------------------------------------------
from app.services.playwright.browser import open_persistent_chromium  # noqa: E402
from app.services.playwright.playground_login import ensure_logged_in, is_logged_in  # noqa: E402
from app.services.playwright.playground_workspace import wait_for_workspace_area  # noqa: E402
from app.services.playwright.playground_monitor import open_files_tab as project_open_files_tab  # noqa: E402

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
USER_ID = int(os.environ.get("INSPECT_USER_ID", "1"))
WORKSPACE_URL = os.environ.get(
    "INSPECT_WORKSPACE_URL",
    "https://genai.stellantis.com/rag/workspaces/a6d5542d-2709-4a3e-84cf-da06be2e40a7",
)
MAX_ROWS = 8
OUTPUT_JSON = Path(__file__).parent / "inspect_workspace_dom_output.json"


def _log(level: str, message: str, **_kw) -> None:
    print(f"[{level.upper()}] {message}")


def _rows_present(page) -> bool:
    try:
        if page.locator("table tbody tr").count() > 0:
            return True
        return page.locator("[role='row']").count() > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main DOM inspection JS
# ---------------------------------------------------------------------------
_INSPECT_JS = r"""
() => {
  const MAX_ROWS = """ + str(MAX_ROWS) + r""";
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const attrOf = (el, ...attrs) => {
    for (const a of attrs) {
      const v = el && el.getAttribute && el.getAttribute(a);
      if (v) return clean(v);
    }
    return '';
  };
  const hasEllipsis = (txt) => /…|\.\.\./.test(txt);

  const result = {
    tables: [],
    role_rows_outside_table: [],
    pagination: [],
    page_size_selector: null,
    notes: [],
  };

  // ---- <table> elements ---------------------------------------------------
  document.querySelectorAll('table').forEach((table, ti) => {
    // thead headers
    const theadEl = table.querySelector('thead');
    const headerEls = theadEl
      ? Array.from(theadEl.querySelectorAll('th, [role="columnheader"]'))
      : Array.from(table.querySelectorAll('tr:first-child th'));

    const headers = headerEls.map((h) => ({
      text: clean(h.innerText || h.textContent || ''),
      ariaLabel: attrOf(h, 'aria-label'),
      title: attrOf(h, 'title'),
      dataFocusId: attrOf(h, 'data-focus-id'),
      class: clean(h.className || '').slice(0, 120),
      scope: attrOf(h, 'scope'),
      // Is this really a body-row <th scope="row"> that the selector grabbed by mistake?
      isBodyRowTh: !theadEl && h.getAttribute('scope') === 'row',
    }));

    // tbody rows
    const tbodyRows = [];
    const rowEls = Array.from(table.querySelectorAll('tbody tr'));
    rowEls.slice(0, MAX_ROWS).forEach((row, ri) => {
      // All direct child cells (td OR th) — Cloudscape uses <th scope="row"> for Name column
      const cellEls = Array.from(
        row.querySelectorAll(':scope > td, :scope > th, :scope > [role="cell"], :scope > [role="gridcell"]')
      );

      const cells = cellEls.map((td, ci) => {
        const innerText = clean(td.innerText || td.textContent || '');
        const ariaLabel = attrOf(td, 'aria-label');
        const titleAttr = attrOf(td, 'title');
        const isNameCell = td.tagName === 'TH' && attrOf(td, 'scope') === 'row';

        // Any child element carrying the full filename as title/aria-label/data-*
        const fullNameAttrs = {};
        td.querySelectorAll('[title], [aria-label], [data-filename], [data-name], [data-testid]').forEach((el) => {
          const t = attrOf(el, 'title');
          const a = attrOf(el, 'aria-label');
          const df = attrOf(el, 'data-filename');
          const dn = attrOf(el, 'data-name');
          const dt = attrOf(el, 'data-testid');
          if (t) fullNameAttrs['title'] = t;
          if (a) fullNameAttrs['aria-label'] = a;
          if (df) fullNameAttrs['data-filename'] = df;
          if (dn) fullNameAttrs['data-name'] = dn;
          if (dt) fullNameAttrs['data-testid'] = dt;
        });

        // Buttons in this cell
        const buttons = Array.from(
          td.querySelectorAll('button, [role="button"], a[role="button"]')
        ).map((b) => ({
          ariaLabel: attrOf(b, 'aria-label'),
          title: attrOf(b, 'title'),
          innerText: clean(b.innerText || b.textContent || ''),
          disabled: b.disabled || b.getAttribute('disabled') !== null,
          class: clean(b.className || '').slice(0, 150),
        }));

        return {
          cellIndex: ci,
          tag: td.tagName,
          scope: attrOf(td, 'scope'),
          isNameCell,
          innerText,
          ariaLabel,
          title: titleAttr,
          isEllipsisTruncated: hasEllipsis(innerText),
          fullNameAttrsFromChildren: fullNameAttrs,
          buttons,
        };
      });

      // Row-level identity attributes
      const rowAttrs = {
        ariaRowIndex: attrOf(row, 'aria-rowindex'),
        dataSelectionItem: attrOf(row, 'data-selection-item'),
        id: row.id || '',
        class: clean(row.className || '').slice(0, 120),
        // Any data-* attributes
        dataAttrs: {},
      };
      Array.from(row.attributes).forEach((a) => {
        if (a.name.startsWith('data-')) rowAttrs.dataAttrs[a.name] = a.value;
      });

      tbodyRows.push({
        index: ri,
        rowAttrs,
        cells,
        // Summarize for quick reading
        nameCellText: (cells.find((c) => c.isNameCell) || cells[0] || {}).innerText || '',
        nameCellEllipsis: (cells.find((c) => c.isNameCell) || cells[0] || {}).isEllipsisTruncated || false,
        statusCellText: (cells[1] || {}).innerText || '',
        deleteButtonAriaLabel: (
          cells.flatMap((c) => c.buttons).find(
            (b) => /delete/i.test(b.ariaLabel || b.title || b.innerText)
          ) || {}
        ).ariaLabel || '',
      });
    });

    // Does the table have a leading checkbox column?
    const hasCheckboxCol = headerEls.some((h) => {
      const t = clean(h.innerText || h.textContent || '');
      return t === '' && h.querySelector('input[type="checkbox"]') !== null;
    }) || (rowEls[0] && rowEls[0].querySelector(':scope > td input[type="checkbox"]') !== null);

    result.tables.push({
      tableIndex: ti,
      theadPresent: !!theadEl,
      headerCount: headers.length,
      headers,
      tbodyRowCount: rowEls.length,
      tbodyRowsDumped: tbodyRows.length,
      tbodyRows,
      hasLeadingCheckboxColumn: hasCheckboxCol,
    });
  });

  // ---- [role="row"] outside <table> ---------------------------------------
  document.querySelectorAll('[role="row"]').forEach((row, ri) => {
    if (row.closest('table')) return;
    if (ri >= MAX_ROWS) return;
    const cells = Array.from(
      row.querySelectorAll('[role="cell"], [role="gridcell"], td, th')
    ).map((td) => ({
      innerText: clean(td.innerText || td.textContent || ''),
      ariaLabel: attrOf(td, 'aria-label'),
    }));
    result.role_rows_outside_table.push({ index: ri, text: clean(row.innerText || ''), cells });
  });

  // ---- Pagination ---------------------------------------------------------
  // Cloudscape: awsui_arrow buttons with angle-left/angle-right icons + page number spans
  document.querySelectorAll(
    'button[class*="awsui_arrow"], [class*="awsui_pagination"] button, [class*="awsui_pagination"] span'
  ).forEach((el) => {
    result.pagination.push({
      tag: el.tagName,
      text: clean(el.innerText || el.textContent || ''),
      ariaLabel: attrOf(el, 'aria-label'),
      disabled: el.tagName === 'BUTTON' ? (el.disabled || el.getAttribute('disabled') !== null) : null,
      class: clean(el.className || '').slice(0, 200),
    });
  });

  // Page size selector
  const pageSizeEl = document.querySelector(
    '[class*="awsui_page-size"] select, select[aria-label*="page size" i], select[aria-label*="items per page" i]'
  );
  if (pageSizeEl) {
    result.page_size_selector = {
      value: pageSizeEl.value,
      options: Array.from(pageSizeEl.options).map((o) => o.value),
    };
  }

  // ---- Notes: structural anomalies detected on the fly --------------------
  // Check if the header selector `thead th, thead [role="columnheader"], tr:first-child th`
  // would accidentally pick up body <th scope="row"> cells (Cloudscape pattern).
  // This is the read_structured_file_rows header detection path.
  document.querySelectorAll('table').forEach((table, ti) => {
    const simulatedHeaders = Array.from(
      table.querySelectorAll('thead th, thead [role="columnheader"], tr:first-child th')
    ).map((h) => ({
      text: clean(h.innerText || h.textContent || ''),
      scope: attrOf(h, 'scope'),
      inThead: !!h.closest('thead'),
    }));
    const spurious = simulatedHeaders.filter((h) => !h.inThead && h.scope === 'row');
    if (spurious.length > 0) {
      result.notes.push({
        note: `Table ${ti}: header selector 'tr:first-child th' picks up body-row <th scope="row"> cells. Spurious headers: ${JSON.stringify(spurious)}`,
      });
    }
    // Check if any Name cell text ends with ellipsis
    const truncatedNames = [];
    table.querySelectorAll('tbody tr').forEach((row) => {
      const nameCell = row.querySelector('th[scope="row"], td:first-child');
      if (nameCell) {
        const txt = clean(nameCell.innerText || nameCell.textContent || '');
        if (hasEllipsis(txt)) truncatedNames.push(txt);
        // Also check title vs innerText mismatch (full name in title)
        const title = attrOf(nameCell, 'title');
        if (title && title !== txt) {
          result.notes.push({
            note: `Table ${ti}: Name cell title='${title}' differs from innerText='${txt}' — title carries full name.`,
          });
        }
      }
    });
    if (truncatedNames.length > 0) {
      result.notes.push({
        note: `Table ${ti}: ${truncatedNames.length} truncated name(s) with ellipsis: ${JSON.stringify(truncatedNames)}`,
      });
    }
  });

  return result;
}
"""


def main() -> None:
    print(f"\n[INFO] Opening persistent Chromium context for user_id={USER_ID}")
    browser = open_persistent_chromium(USER_ID)
    page = browser.page
    payload = {
        "workspace_playground_url": WORKSPACE_URL,
        "url": "https://genai.stellantis.com/",
        "manual_login_timeout_minutes": int(os.environ.get("INSPECT_LOGIN_MIN", "4")),
    }
    try:
        print(f"[INFO] Navigating to: {WORKSPACE_URL}")
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        # Check login state; if session expired, stop and report
        if not is_logged_in(page):
            print("\n[WARN] SESSION NOT LOGGED IN.")
            print("[WARN] A login screen (or redirect) is showing instead of the workspace.")
            print("[WARN] Stopping as instructed -- do NOT attempt automatic login.")
            print("[WARN] Manual SSO re-login is required before this inspection can proceed.")
            print(f"[WARN] Current URL: {page.url}")
            return

        print("[INFO] Session is logged in.")
        # Re-navigate to workspace after confirming login
        print(f"[INFO] Re-navigating to workspace: {WORKSPACE_URL}")
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        try:
            wait_for_workspace_area(page, "files", timeout_ms=20000)
        except Exception:
            pass

        # Open Files tab and wait for rows
        print("[INFO] Opening Files tab and waiting for table rows...")
        deadline = time.time() + 45
        while time.time() < deadline:
            try:
                project_open_files_tab(page, _log)
            except Exception:
                pass
            if _rows_present(page):
                break
            time.sleep(2)
        # Extra wait for virtualization/Ajax
        rows_deadline = time.time() + 20
        while time.time() < rows_deadline and not _rows_present(page):
            time.sleep(1.5)

        # Diagnostics
        try:
            n_table = page.locator("table").count()
            n_tr = page.locator("table tbody tr").count()
            n_role = page.locator("[role='row']").count()
            print(f"\n[DIAG] Current URL: {page.url}")
            print(f"[DIAG] <table> count={n_table}  tbody tr count={n_tr}  [role=row] count={n_role}")
            body_snippet = " ".join(page.locator("body").inner_text(timeout=4000).split())[:600]
            print(f"[DIAG] body text (600 chars): {body_snippet}")
        except Exception as exc:
            print(f"[DIAG] Failed to collect diagnostics: {exc}")

        if not _rows_present(page):
            print("\n[ERROR] Table rows not found after waiting. The workspace may be empty,")
            print("[ERROR] or the Files tab did not render. Check DIAG output above.")
            return

        print("\n[INFO] Extracting DOM...")
        dom = page.evaluate(_INSPECT_JS)

        # ---- Print findings ------------------------------------------------
        print("\n" + "=" * 72)
        print("DOM INSPECTION RESULTS -- READ-ONLY")
        print("=" * 72)

        for table in dom.get("tables", []):
            ti = table["tableIndex"]
            print(f"\n=== TABLE {ti} ===")
            print(f"  thead present: {table['theadPresent']}")
            print(f"  Header count (as returned by JS): {table['headerCount']}")
            print(f"  tbody row count (all): {table['tbodyRowCount']}")
            print(f"  Has leading checkbox column: {table['hasLeadingCheckboxColumn']}")
            print(f"  Headers:")
            for h in table["headers"]:
                flag = " *** BODY-ROW TH (spurious!) ***" if not h.get("inThead", True) and h.get("scope") == "row" else ""
                print(f"    text='{h['text']}'  scope='{h['scope']}'  dataFocusId='{h['dataFocusId']}'{flag}")

            print(f"\n  Body rows ({table['tbodyRowsDumped']} dumped):")
            for row in table.get("tbodyRows", []):
                print(f"\n  -- Row {row['index']} --")
                ra = row["rowAttrs"]
                print(f"     row class='{ra['class']}'")
                print(f"     aria-rowindex='{ra['ariaRowIndex']}'  data-selection-item='{ra['dataSelectionItem']}'  id='{ra['id']}'")
                da = ra.get("dataAttrs", {})
                if da:
                    print(f"     data-* attrs: {da}")
                print(f"     [SUMMARY] Name cell text: '{row['nameCellText']}'")
                print(f"     [SUMMARY] Name cell has ellipsis: {row['nameCellEllipsis']}")
                print(f"     [SUMMARY] Status cell text: '{row['statusCellText']}'")
                print(f"     [SUMMARY] Delete button aria-label: '{row['deleteButtonAriaLabel']}'")
                print(f"     Cells ({len(row['cells'])}):")
                for cell in row["cells"]:
                    truncated_flag = "  <-- TRUNCATED WITH ELLIPSIS" if cell["isEllipsisTruncated"] else ""
                    name_flag = "  <-- NAME CELL (th scope=row)" if cell["isNameCell"] else ""
                    print(f"       [{cell['cellIndex']}] tag={cell['tag']} scope='{cell['scope']}'  text='{cell['innerText'][:80]}'{truncated_flag}{name_flag}")
                    if cell["ariaLabel"]:
                        print(f"             cell aria-label='{cell['ariaLabel']}'")
                    if cell["title"]:
                        print(f"             cell title='{cell['title']}'")
                    full_name_attrs = cell.get("fullNameAttrsFromChildren", {})
                    if full_name_attrs:
                        print(f"             FULL-NAME child attrs: {full_name_attrs}")
                    for btn in cell.get("buttons", []):
                        print(f"             BUTTON: aria-label='{btn['ariaLabel']}'  title='{btn['title']}'  text='{btn['innerText'][:40]}'  disabled={btn['disabled']}")

        print("\n--- role=row outside <table> ---")
        rrows = dom.get("role_rows_outside_table", [])
        if rrows:
            for rr in rrows:
                print(f"  [{rr['index']}] text='{rr['text'][:80]}'")
        else:
            print("  (none)")

        print("\n--- Pagination controls ---")
        pag = dom.get("pagination", [])
        if pag:
            for p in pag:
                print(f"  tag={p['tag']}  text='{p['text']}'  aria-label='{p['ariaLabel']}'  disabled={p['disabled']}")
                print(f"    class='{p['class'][:100]}'")
        else:
            print("  (none found)")

        ps = dom.get("page_size_selector")
        if ps:
            print(f"\n--- Page size selector: current={ps['value']} options={ps['options']} ---")

        print("\n--- STRUCTURAL NOTES (anomalies detected) ---")
        notes = dom.get("notes", [])
        if notes:
            for n in notes:
                print(f"  NOTE: {n['note']}")
        else:
            print("  (no anomalies detected)")

        # Save JSON
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(dom, f, ensure_ascii=False, indent=2)
        print(f"\n[INFO] Full JSON saved to: {OUTPUT_JSON}")
        print("[INFO] Inspection complete. NO destructive actions were taken.")

    finally:
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\nPress ENTER to close the browser...")
        except Exception:
            pass
        browser.close()
        print("[INFO] Browser closed.")


if __name__ == "__main__":
    main()
