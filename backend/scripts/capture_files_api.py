r"""
capture_files_api.py -- Fonte AUTORITATIVA da lista de arquivos de um workspace.

Em vez de raspar o DOM (nao confiavel no Cloudscape), captura as respostas de
rede (XHR/fetch) que o Playground usa para listar os arquivos do workspace e
extrai os nomes a partir do JSON. Somente leitura: nao clica em nada.

Uso:
    $env:INSPECT_WORKSPACE_URL = "https://genai.stellantis.com/rag/workspaces/<id>"
    & ".\backend\.venv\Scripts\python.exe" ".\backend\scripts\capture_files_api.py"
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _set_browsers_path() -> None:
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]).exists():
        return
    for cand in (BACKEND_DIR / "ms-playwright",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"):
        if cand.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(cand)
            return


_set_browsers_path()
_env = BACKEND_DIR / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(_env))
    except ImportError:
        pass

from app.services.playwright.browser import open_persistent_chromium  # noqa: E402

USER_ID = int(os.environ.get("INSPECT_USER_ID", "1"))
WORKSPACE_URL = os.environ.get(
    "INSPECT_WORKSPACE_URL",
    "https://genai.stellantis.com/rag/workspaces/44285aae-872d-442d-9943-0147f71b01fc",
)

# Nomes de arquivo extraidos de qualquer JSON que pareca uma listagem de arquivos.
NAME_KEYS = ("file_name", "fileName", "filename", "name", "document_name",
             "documentName", "title", "originalName", "original_name")
_FILENAME_RE = re.compile(r'"([^"\\]{1,200}\.(?:docx|pdf|xlsx|csv|txt|pptx|doc|xls))"', re.IGNORECASE)


def _walk_collect(obj, out: set[str]) -> None:
    """Percorre JSON e coleta valores de chaves de nome que terminem em extensao."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in NAME_KEYS and isinstance(v, str) and "." in v:
                out.add(v)
            else:
                _walk_collect(v, out)
    elif isinstance(obj, list):
        for it in obj:
            _walk_collect(it, out)


def main() -> None:
    print(f"[INFO] Abrindo Chromium (user {USER_ID}) -> {WORKSPACE_URL}")
    browser = open_persistent_chromium(USER_ID)
    page = browser.page

    api_names: set[str] = set()
    regex_names: set[str] = set()
    hit_urls: set[str] = set()

    def on_response(resp):
        try:
            ct = (resp.headers or {}).get("content-type", "")
            url = resp.url
            if "json" not in ct.lower():
                return
            body = resp.text()
            if not body:
                return
            # Heuristica: so processa respostas que mencionam extensoes de arquivo.
            if not _FILENAME_RE.search(body):
                return
            hit_urls.add(url)
            for m in _FILENAME_RE.finditer(body):
                regex_names.add(m.group(1))
            try:
                data = json.loads(body)
                _walk_collect(data, api_names)
            except Exception:
                pass
        except Exception:
            pass

    page.on("response", on_response)

    try:
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        # Reabre para garantir o disparo das chamadas de listagem da aba Files.
        page.goto(WORKSPACE_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        time.sleep(4)

        print("\n=== URLs de API que retornaram nomes de arquivo ===")
        for u in sorted(hit_urls):
            print(f"  {u}")

        merged = sorted(api_names | regex_names)
        print(f"\n=== ARQUIVOS (fonte API, autoritativa) — total {len(merged)} ===")
        for n in merged:
            print(f"  {n}")

        target = os.environ.get("CHECK_NAME", "CONTRATO")
        present = [n for n in merged if target.lower() in n.lower()]
        print(f"\n=== Checagem '{target}' ===")
        print(f"  {'PRESENTE: ' + str(present) if present else 'AUSENTE (nao encontrado na API)'}")
    finally:
        browser.close()
        print("[INFO] Navegador fechado.")


if __name__ == "__main__":
    main()
