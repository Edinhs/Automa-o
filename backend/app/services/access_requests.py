from __future__ import annotations

import os
import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, current_environment, runtime_path, settings
from app.models.agent import AgentTask
from app.services.playwright.browser import open_persistent_chromium

_DEFAULT_COLUMN = "IDRede"
_ENGINEERS_CACHE: dict[str, dict[str, object]] = {}
_GRID_NETWORK_IDS_JS = """
({ targetColumn }) => {
  const clean = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
  const norm = (v) => clean(v).toUpperCase();
  const target = norm(targetColumn || 'IDRede');
  const textOf = (el) => {
    if (!el) return '';
    const parts = [el.innerText || el.textContent || ''];
    if (el.getAttribute) {
      parts.push(el.getAttribute('aria-label') || '');
      parts.push(el.getAttribute('title') || '');
    }
    if (el.querySelectorAll) {
      el.querySelectorAll('[aria-label], [title]').forEach((c) => {
        parts.push(c.getAttribute('aria-label') || '');
        parts.push(c.getAttribute('title') || '');
      });
    }
    return clean(parts.filter(Boolean).join(' '));
  };
  const headerIndex = (headers) => {
    for (let i = 0; i < headers.length; i += 1) {
      if (norm(headers[i]) === target) return i;
    }
    for (let i = 0; i < headers.length; i += 1) {
      if (norm(headers[i]).includes(target)) return i;
    }
    return -1;
  };
  const readRows = (rows, idx) => {
    const values = [];
    rows.forEach((row) => {
      const cells = Array.from(row.querySelectorAll(':scope > td, :scope > th, :scope > [role="cell"], :scope > [role="gridcell"]'));
      if (!cells.length) return;
      if (idx >= 0 && idx < cells.length) {
        values.push(textOf(cells[idx]));
      }
    });
    return values;
  };

  const tables = Array.from(document.querySelectorAll('table'));
  for (const table of tables) {
    const headers = Array.from(table.querySelectorAll('thead th, thead [role="columnheader"], tr:first-child th')).map(textOf);
    const idx = headerIndex(headers);
    if (idx < 0) continue;
    const rows = Array.from(table.querySelectorAll('tbody tr, [role="row"]')).filter((row) =>
      row.querySelector(':scope > td, :scope > th, :scope > [role="cell"], :scope > [role="gridcell"]')
    );
    const values = readRows(rows, idx);
    if (values.length) return { found: true, values };
  }

  const grids = Array.from(document.querySelectorAll('[role="grid"], [role="table"]'));
  for (const grid of grids) {
    const headers = Array.from(grid.querySelectorAll('[role="columnheader"]')).map(textOf);
    const idx = headerIndex(headers);
    if (idx < 0) continue;
    const rows = Array.from(grid.querySelectorAll('[role="row"]'));
    const values = readRows(rows, idx);
    if (values.length) return { found: true, values };
  }
  return { found: false, values: [] };
}
"""


def _ensure_playwright_browsers_path() -> None:
    existing = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if existing and Path(existing).exists():
        return
    bundled = BACKEND_DIR / "ms-playwright"
    if bundled.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled)


def count_unique_requesters(raw_values: list[str | None]) -> int:
    normalized = {
        str(value or "").strip().upper()
        for value in raw_values
        if str(value or "").strip()
    }
    return len(normalized)


def _fallback_engineers_count_from_db(db: Session) -> int:
    engineers: set[str] = set()
    for (payload_json,) in db.query(AgentTask.payload_json).filter(
        AgentTask.is_deleted == False,
        AgentTask.task_type == "add_playground_user_to_workspace",
        AgentTask.status == "completed",
    ).all():
        try:
            payload = json.loads(payload_json or "{}")
        except (TypeError, ValueError):
            payload = {}
        nid = str(payload.get("network_id") or payload.get("user_identifier") or "").strip().upper()
        if nid:
            engineers.add(nid)
    return len(engineers)


def _cache_ttl() -> timedelta:
    minutes = max(0, int(settings.REPORT_ENGINEERS_CACHE_MINUTES or 0))
    return timedelta(minutes=minutes)


def _cache_key() -> str:
    return current_environment()


def _read_cached_count(now: datetime) -> int | None:
    entry = _ENGINEERS_CACHE.get(_cache_key()) or {}
    count = entry.get("count")
    fetched_at = entry.get("fetched_at")
    if not isinstance(count, int) or not isinstance(fetched_at, datetime):
        return None
    if now - fetched_at <= _cache_ttl():
        return count
    return None


def _read_stale_cached_count() -> int | None:
    entry = _ENGINEERS_CACHE.get(_cache_key()) or {}
    count = entry.get("count")
    return count if isinstance(count, int) else None


def _write_cached_count(count: int, now: datetime, source: str) -> int:
    _ENGINEERS_CACHE[_cache_key()] = {"count": int(count), "fetched_at": now, "source": source}
    return int(count)


def _scroll_sharepoint_grid(page, *, horizontal: int | None = None, vertical: int | None = None) -> None:
    try:
        page.evaluate(
            """({ horizontal, vertical }) => {
              const seen = new Set();
              const candidates = Array.from(document.querySelectorAll('*')).filter((el) => {
                if (!(el instanceof HTMLElement)) return false;
                const key = `${el.tagName}:${el.clientWidth}:${el.clientHeight}`;
                if (seen.has(key)) return false;
                seen.add(key);
                const canX = horizontal !== null && el.scrollWidth > el.clientWidth + 50;
                const canY = vertical !== null && el.scrollHeight > el.clientHeight + 50;
                return canX || canY;
              });
              candidates.forEach((el) => {
                if (horizontal !== null) el.scrollLeft = horizontal;
                if (vertical !== null) el.scrollTop = vertical;
              });
              if (vertical !== null) window.scrollTo(0, vertical);
            }""",
            {"horizontal": horizontal, "vertical": vertical},
        )
    except Exception:
        return


def fetch_access_request_network_ids(*, timeout_ms: int = 45000) -> list[str] | None:
    """Le a coluna IDRede da lista SharePoint via sessao persistente do Teams.

    Usa a Sync API do Playwright; em caminhos async, o chamador pode encapsular esta funcao em
    run_in_threadpool. Em qualquer falha/timeout/seletor ausente, retorna None.
    """
    _ensure_playwright_browsers_path()
    browser = None
    try:
        session_dir = runtime_path("TEAMS_BROWSER_SESSION_PATH")
        browser = open_persistent_chromium(
            user_id=1,
            headless=bool(settings.PLAYWRIGHT_HEADLESS),
            session_dir=session_dir,
        )
        page = browser.page
        page.set_default_timeout(timeout_ms)
        page.goto(
            str(settings.REPORT_ACCESS_REQUESTS_LIST_URL or "").strip(),
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        page.wait_for_timeout(1500)
        target_column = str(settings.REPORT_ACCESS_REQUESTS_COLUMN or _DEFAULT_COLUMN).strip() or _DEFAULT_COLUMN
        deadline = datetime.utcnow() + timedelta(milliseconds=max(timeout_ms, 1))
        collected: list[str] = []
        seen_snapshots: set[tuple[str, ...]] = set()
        stable_rounds = 0
        for horizontal in (0, 2500):
            _scroll_sharepoint_grid(page, horizontal=horizontal)
            page.wait_for_timeout(400)
            for step in range(20):
                if datetime.utcnow() >= deadline:
                    break
                try:
                    data = page.evaluate(_GRID_NETWORK_IDS_JS, {"targetColumn": target_column}) or {}
                except Exception:
                    data = {}
                values = [str(v) for v in (data.get("values") or []) if str(v).strip()]
                found = bool(data.get("found"))
                if values:
                    collected.extend(values)
                    snapshot = tuple(values)
                    if snapshot in seen_snapshots:
                        stable_rounds += 1
                    else:
                        seen_snapshots.add(snapshot)
                        stable_rounds = 0
                elif found:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                if stable_rounds >= 2:
                    break
                next_vertical = (step + 1) * 1400
                _scroll_sharepoint_grid(page, vertical=next_vertical)
                page.wait_for_timeout(300)
            if collected:
                break
        return collected or None
    except Exception:
        return None
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def get_engineers_count(db: Session, *, now: datetime | None = None) -> int:
    now_utc = now or datetime.utcnow()
    cached = _read_cached_count(now_utc)
    if cached is not None:
        return cached

    raw_values = fetch_access_request_network_ids()
    if raw_values is not None:
        return _write_cached_count(count_unique_requesters(raw_values), now_utc, "sharepoint")

    stale_cached = _read_stale_cached_count()
    if stale_cached is not None:
        return stale_cached

    fallback = _fallback_engineers_count_from_db(db)
    return _write_cached_count(fallback, now_utc, "db_fallback")
