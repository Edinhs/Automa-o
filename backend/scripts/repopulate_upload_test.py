r"""
repopulate_upload_test.py -- Teste AO VIVO do upload em lote (monitoramento de pasta -> workspace).

Gera N arquivos .docx validos localmente, organiza em lotes e chama
upload_files_to_workspace para re-adiciona-los ao workspace. Exercita o caminho real
de upload em lote (inclui o fix de timeout entre lotes da Tarefa 1). Verificacao de
quantos foram adicionados deve ser feita pela API (capture_files_api.py) antes/depois.

Uso (raiz do repo):
    $env:INSPECT_WORKSPACE_URL = "https://genai.stellantis.com/rag/workspaces/<id>"
    & ".\backend\.venv\Scripts\python.exe" ".\backend\scripts\repopulate_upload_test.py"

Variaveis opcionais: N_FILES (padrao 7), BATCH_SIZE (padrao 3), NAME_PREFIX (padrao repop_test).
"""
from __future__ import annotations

import os
import sys
import time
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _set_browsers_path() -> None:
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]).exists():
        return
    for cand in (BACKEND_DIR / "ms-playwright", Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"):
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

from app.services.playwright.playground_upload import upload_files_to_workspace  # noqa: E402

USER_ID = int(os.environ.get("INSPECT_USER_ID", "1"))
WORKSPACE_URL = os.environ.get(
    "INSPECT_WORKSPACE_URL",
    "https://genai.stellantis.com/rag/workspaces/44285aae-872d-442d-9943-0147f71b01fc",
)
N_FILES = int(os.environ.get("N_FILES", "7"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "3"))
NAME_PREFIX = os.environ.get("NAME_PREFIX", "repop_test")

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>'
)


def _make_docx(path: Path, text: str) -> None:
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", doc)


def _log(level: str, message: str, **_kw) -> None:
    print(f"[{level.upper()}] {message}")


def main() -> None:
    stamp = time.strftime("%H%M%S")
    folder = Path(os.environ.get("TEMP", str(BACKEND_DIR))) / f"hub_repop_{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Gerando {N_FILES} .docx em {folder}")

    files: list[dict] = []
    for i in range(1, N_FILES + 1):
        name = f"{NAME_PREFIX}_{stamp}_{i:02d}.docx"
        p = folder / name
        _make_docx(p, f"Arquivo de teste de repopulacao {name} (lote)")
        # batch_folder_path agrupa em lotes; usamos rotulos logicos lote_NNN.
        lote = (i - 1) // BATCH_SIZE + 1
        files.append({
            "path": str(p),
            "file_name": name,
            "file_id": name,
            "batch_folder_path": f"lote_{lote:03d}",
            "batch_number": lote,
        })

    n_batches = (N_FILES + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"[INFO] {N_FILES} arquivos -> {n_batches} lote(s) de ate {BATCH_SIZE}.")
    print(f"[INFO] Nomes: {[f['file_name'] for f in files]}")

    payload = {
        "workspace_name": str(WORKSPACE_URL).rstrip('/').split('/')[-1].split('?')[0],
        "workspace_playground_url": WORKSPACE_URL,
        "url": "https://genai.stellantis.com/",
        "files": files,
        "batch_size": BATCH_SIZE,
    }

    print("\n[INFO] >>> Iniciando upload_files_to_workspace (envio REAL em lote) <<<\n")
    result = upload_files_to_workspace(
        task_id=0,
        user_id=USER_ID,
        payload=payload,
        log=_log,
        should_continue=None,
        on_batch_uploaded=lambda bn, bf, items: print(f"[CALLBACK] lote {bn} confirmado: {[i.get('file_name') for i in items]}"),
        on_file_error=lambda fid, msg: print(f"[CALLBACK-ERRO] {fid}: {msg}"),
    )

    print("\n========================================================================")
    print("RESULTADO upload_files_to_workspace")
    print("========================================================================")
    print(f"  status: {result.get('status')}")
    up = result.get("uploaded") or result.get("uploaded_files") or []
    print(f"  enviados (count): {len(up)}")
    print(f"  result keys: {sorted(result.keys())}")
    print(f"\n[INFO] Confirme a inclusao pela API: capture_files_api.py (diff antes/depois). Nomes esperados:")
    for f in files:
        print(f"  + {f['file_name']}")


if __name__ == "__main__":
    main()
