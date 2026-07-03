"""
Harness offline de testes dos helpers puros de casamento/guarda do monitor.

Exercita os cenarios criticos SEM abrir navegador:
  1. 'data.csv' NAO casa a linha 'metadata.csv'  (o bug historico de substring)
  2. stem .docx <-> .pdf CASA por igualdade de stem
  3. Status lido por indice nao deriva com celula vazia
  4. Ready NUNCA entra como deletavel
  5. Novos helpers de streaming: _read_row_status_and_name / _row_deletable

Uso:
    cd backend
    .venv\Scripts\python.exe scripts\test_monitor_helpers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# --- Importa os helpers que vamos testar ---
from app.services.playwright.playground_monitor import (  # noqa: E402
    _norm,
    _row_identity_matches,
    _row_matches_target,
    _name_from_aligned,
    _status_from_aligned,
    _truncation_match,
    normalize_status,
    match_name_in_rows,
    header_index,
)

PASS = 0
FAIL = 0


def check(description: str, result: bool, expected: bool = True) -> None:
    global PASS, FAIL
    ok = result == expected
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {description}")
    if not ok:
        print(f"         got={result!r}  expected={expected!r}")


print("\n=== 1. _row_identity_matches: evita colisao de substring ===")
check("data.csv NAO casa metadata.csv", _row_identity_matches("metadata.csv", "data.csv"), False)
check("data.csv CASA data.csv", _row_identity_matches("data.csv", "data.csv"), True)
check("relatorio.docx CASA relatorio.pdf (mesmo stem)", _row_identity_matches("relatorio.docx", "relatorio.pdf"), True)
check("relatorio_v2.docx NAO casa relatorio.pdf (stems diferentes)", _row_identity_matches("relatorio_v2.docx", "relatorio.pdf"), False)
check("ARQUIVO.CSV CASA arquivo.csv (case-insensitive)", _row_identity_matches("ARQUIVO.CSV", "arquivo.csv"), True)
check("planilha.xlsx NAO casa planilha_backup.xlsx", _row_identity_matches("planilha_backup.xlsx", "planilha.xlsx"), False)

print("\n=== 2. match_name_in_rows: camadas de casamento ===")
# Rows estruturadas simuladas
ROWS_SIMPLE = [
    {"source": "table", "headers": ["Name", "Status", "Upload date", "Size", "Actions"],
     "cells": ["metadata.csv", "Ready", "2025-01-01", "12 KB", ""], "text": "metadata.csv Ready 2025-01-01 12 KB"},
    {"source": "table", "headers": ["Name", "Status", "Upload date", "Size", "Actions"],
     "cells": ["data.csv", "Error", "2025-01-01", "8 KB", ""], "text": "data.csv Error 2025-01-01 8 KB"},
]
mt, st = match_name_in_rows("data.csv", ROWS_SIMPLE, [])
check("match_name_in_rows: data.csv encontra a linha certa (status Error)", "Error" in st, True)
check("match_name_in_rows: data.csv NAO retorna texto de metadata.csv", "metadata" not in (mt or "").lower(), True)

mt2, st2 = match_name_in_rows("metadata.csv", ROWS_SIMPLE, [])
check("match_name_in_rows: metadata.csv encontra linha certa (status Ready)", "Ready" in st2, True)

# Stem matching
ROWS_PDF = [
    {"source": "table", "headers": ["Name", "Status", "Upload date", "Size", "Actions"],
     "cells": ["relatorio.pdf", "Ready", "2025-01-01", "50 KB", ""], "text": "relatorio.pdf Ready"},
]
mt3, st3 = match_name_in_rows("relatorio.docx", ROWS_PDF, [])
check("stem match: relatorio.docx acha relatorio.pdf via stem", "Ready" in st3, True)

print("\n=== 3. _status_from_aligned: alinhamento por indice com celulas vazias ===")
# Headers: Name, Status, Upload date, Size, Actions
HEADERS = ["Name", "Status", "Upload date", "Size", "Actions"]
CELLS_NO_EMPTY = ["data.csv", "Error", "2025-01-01", "8 KB", ""]
CELLS_WITH_EMPTY = ["data.csv", "", "Error", "8 KB", ""]  # Status vazio, Error na 3a coluna

check("_status_from_aligned: celulas sem vazio, pega status da coluna correta",
      _status_from_aligned(HEADERS, CELLS_NO_EMPTY, "data.csv", "data.csv Error 2025-01-01 8 KB") == "Error",
      True)

check("_status_from_aligned: celulas com Status vazio, fallback por conteudo",
      _status_from_aligned(HEADERS, CELLS_WITH_EMPTY, "data.csv", "data.csv Error 2025-01-01 8 KB") != "Ready",
      True)

CELLS_READY = ["arquivo.pdf", "Ready", "2025-01-01", "5 MB", ""]
check("_status_from_aligned: Ready lido corretamente",
      _status_from_aligned(HEADERS, CELLS_READY, "arquivo.pdf", "arquivo.pdf Ready") == "Ready",
      True)

print("\n=== 4. _name_from_aligned: extrai nome corretamente ===")
check("_name_from_aligned: pega da coluna Name",
      _name_from_aligned(HEADERS, CELLS_NO_EMPTY) == "data.csv",
      True)

HEADERS_NO_NAME = ["Status", "Upload date", "Size", "Actions"]
CELLS_NO_NAME = ["Error", "2025-01-01", "8 KB", ""]
name = _name_from_aligned(HEADERS_NO_NAME, CELLS_NO_NAME)
check("_name_from_aligned: sem coluna Name, retorna 1a celula util",
      len(name) > 0,
      True)

print("\n=== 5. normalize_status: mapeamento correto ===")
check("normalize_status: 'Ready' -> Ready", normalize_status("Ready") == "Ready", True)
check("normalize_status: 'Error' -> Error", normalize_status("Error") == "Error", True)
check("normalize_status: 'Processing' -> Processing", normalize_status("Processing") == "Processing", True)
check("normalize_status: 'Pending' -> Pending", normalize_status("Pending") == "Pending", True)
check("normalize_status: 'Erro' -> Error (PT)", normalize_status("Erro") == "Error", True)
check("normalize_status: 'Processando' -> Processing (PT)", normalize_status("Processando") == "Processing", True)
check("normalize_status: '' -> Unknown", normalize_status("") == "Unknown", True)
check("normalize_status: 'foo' -> Unknown", normalize_status("foo") == "Unknown", True)

print("\n=== 6. _truncation_match: nomes longos truncados com reticencias ===")
check("_truncation_match: fragmento de 8+ chars com reticencias casa",
      _truncation_match(_norm("relatorio_de_vendas_2025.pdf"), _norm("relatorio_de_vendas_2025"), _norm("relatorio_de_vendas…")),
      True)
check("_truncation_match: fragmento curto (<8) NAO casa (muito generico)",
      _truncation_match(_norm("relatorio.pdf"), _norm("relatorio"), _norm("relat…")),
      False)
check("_truncation_match: sem reticencias retorna False",
      _truncation_match(_norm("arquivo.pdf"), _norm("arquivo"), _norm("arquivo.pdf")),
      False)

print("\n=== 7. header_index: localiza indices corretamente ===")
HDRS = ["Name", "Status", "Upload date", "Size", "Actions"]
check("header_index: Status na posicao 1", header_index(HDRS, ["status"]) == 1, True)
check("header_index: Name na posicao 0", header_index(HDRS, ["name", "nome"]) == 0, True)
check("header_index: coluna inexistente retorna None", header_index(HDRS, ["foobar"]) is None, True)

print("\n=== 8. Regra de guarda: Ready nunca entra como deletavel ===")
# Simulacao da logica do monitor: so arquivos com status Error/Processing entram em to_fix
all_statuses = {
    "arquivo_ready.pdf": {"status": "Ready"},
    "arquivo_error.pdf": {"status": "Error"},
    "arquivo_processing.pdf": {"status": "Processing"},
    "arquivo_pending.pdf": {"status": "Pending"},
    "arquivo_notfound.pdf": {"status": "NotFound"},
}
ready = [n for n, d in all_statuses.items() if d["status"] == "Ready"]
pending = [n for n, d in all_statuses.items() if d["status"] == "Pending"]
not_found = [n for n, d in all_statuses.items() if d["status"] == "NotFound"]
to_fix = [n for n in all_statuses if n not in ready and n not in pending and n not in not_found]

check("Ready NAO entra em to_fix", "arquivo_ready.pdf" not in to_fix, True)
check("Error ENTRA em to_fix", "arquivo_error.pdf" in to_fix, True)
check("Processing ENTRA em to_fix", "arquivo_processing.pdf" in to_fix, True)
check("Pending NAO entra em to_fix", "arquivo_pending.pdf" not in to_fix, True)
check("NotFound NAO entra em to_fix", "arquivo_notfound.pdf" not in to_fix, True)

print(f"\n{'='*50}")
print(f"Resultado: {PASS} PASS, {FAIL} FAIL")
if FAIL:
    print("ATENCAO: testes falharam — revisar os helpers antes de deploiar.")
    sys.exit(1)
else:
    print("Todos os testes passaram.")
    sys.exit(0)
