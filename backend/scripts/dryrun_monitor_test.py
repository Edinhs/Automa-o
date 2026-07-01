r"""
Dry-run do monitor REAL contra um workspace ao vivo — NAO DESTRUTIVO.

Chama monitor_workspace_files_status(..., payload com monitor_dry_run=True). O monitor
le a tabela linha-a-linha, classifica cada arquivo (Ready/Processing/Error) e LOGA a
decisao de delecao por arquivo, mas NUNCA clica em deletar nem reenvia. Serve para provar,
ao vivo, que a logica nova nunca tocaria um arquivo Ready e so marcaria Error/Processing.

Uso:
    cd backend
    .venv\Scripts\python.exe scripts\dryrun_monitor_test.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_ms_playwright = BACKEND_DIR / "ms-playwright"
if _ms_playwright.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_ms_playwright))

_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(str(_env_file))

from app.services.playwright.playground_monitor import monitor_workspace_files_status  # noqa: E402

USER_ID = int(os.environ.get("INSPECT_USER_ID", "1"))
WORKSPACE_URL = os.environ.get(
    "INSPECT_WORKSPACE_URL",
    "https://genai.stellantis.com/rag/workspaces/44285aae-872d-442d-9943-0147f71b01fc?tab=file",
)
WORKSPACE_NAME = os.environ.get("INSPECT_WORKSPACE_NAME", "TEST1")

# Nomes esperados (os 4 arquivos atualmente em Processing no TEST1). Se algum nome nao casar
# uma linha, ele aparece como NotFound — ainda assim NAO-DESTRUTIVO.
EXPECTED_FILES = [
    "CONTRATO DE COMPRA E VENDA DE VEÍCULO ALIENADO.docx",
    "DiagramaDeClasses.docx",
    "Exercicio 3.docx",
    "PRESENT SIMPLES HOMEWORK.docx",
]


def _log(level: str, message: str, file_id=None, metadata=None) -> None:
    extra = ""
    if metadata:
        extra = f"  | {metadata}"
    print(f"[{level.upper()}] {message}{extra}")


def main() -> None:
    payload = {
        "workspace_name": WORKSPACE_NAME,
        "workspace_playground_url": WORKSPACE_URL,
        "url": "https://genai.stellantis.com/",
        "user_id": USER_ID,
        "files": [{"file_name": name} for name in EXPECTED_FILES],
        # DRY-RUN: nada e deletado/reenviado. Forca o modo independente do .env.
        "monitor_dry_run": True,
        # Pula a espera (monitoramento imediato) e abre o navegador visivel.
        "monitoring_timeout_minutes": 0,
        "headless": False,
        # Fail-fast: se cair em tela de login, falha em 1 min em vez de esperar 10 min.
        "manual_login_timeout_minutes": 1,
    }
    print("=" * 70)
    print("DRY-RUN DO MONITOR (NAO-DESTRUTIVO) — nenhum delete sera clicado")
    print(f"Workspace: {WORKSPACE_NAME}  ({WORKSPACE_URL})")
    print(f"Arquivos esperados: {len(EXPECTED_FILES)}")
    print("=" * 70)

    result = monitor_workspace_files_status(
        task_id=0, user_id=USER_ID, payload=payload, log=_log, should_continue=None
    )

    print("\n" + "=" * 70)
    print("RESULTADO (DRY-RUN)")
    print("=" * 70)
    for key in ("dry_run", "would_delete", "skipped_ready", "skipped_status",
                "ready", "ambiguous", "absent", "manual_review", "to_resend"):
        if key in result:
            print(f"  {key}: {result.get(key)}")
    print("\n  statuses lidos:")
    for name, data in (result.get("statuses") or {}).items():
        print(f"    - {name}: {data.get('status')}")


if __name__ == "__main__":
    main()
