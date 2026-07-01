r"""
test_pdf_resend_flow.py -- Testes deterministicos (sem navegador) do fluxo NOVO de PDF:

  1. _pdf_dir_for_resend: apos o monitoramento, a pasta 'PDF' fica DENTRO da pasta de
     staging do ciclo (temp_folder_path), junto com os lotes. Fallbacks: derivar do
     temp_path do arquivo (parent do lote) e, por ultimo, a pasta monitorada.
  2. convert_to_pdf_in_folder (ramo nao-PDF): mantem na pasta PDF TANTO uma copia do
     arquivo original (error/processing) QUANTO o PDF convertido.

Uso: a partir de backend/  ->  .venv\Scripts\python.exe scripts\test_pdf_resend_flow.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.cli.local_agent import _pdf_dir_for_resend  # noqa: E402
import app.services.playwright.playground_upload as pu  # noqa: E402


def _log(*_a, **_k) -> None:
    pass


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def test_resend_dir_uses_staging_run_dir() -> None:
    # temp_folder_path = diretorio de staging do ciclo (contem os lote_NNN) -> {staging}/PDF
    payload = {"temp_folder_path": "C:/tmp/auto_123_20260101_000000_000000", "folder_path": "C:/monitorada"}
    d = _pdf_dir_for_resend(payload, [], [])
    assert d and _norm(d).endswith("auto_123_20260101_000000_000000/PDF"), d
    print("[PASS] _pdf_dir_for_resend usa o diretorio de staging (junto com os lotes)")


def test_resend_dir_fallback_from_temp_path() -> None:
    # Sem temp_folder_path: deriva do temp_path do arquivo (.../staging/lote_001/x -> .../staging/PDF)
    files = [{"file_name": "rel.docx", "temp_path": "C:/tmp/run_abc/lote_001/rel.docx"}]
    d = _pdf_dir_for_resend({}, files, ["rel.docx"])
    assert d and _norm(d).endswith("run_abc/PDF"), d
    print("[PASS] _pdf_dir_for_resend deriva o staging do temp_path do lote")


def test_resend_dir_last_resort_folder() -> None:
    # Sem staging nem temp_path: ultimo recurso e a pasta monitorada/PDF
    d = _pdf_dir_for_resend({"folder_path": "C:/monitorada"}, [], [])
    assert d and _norm(d).endswith("monitorada/PDF"), d
    print("[PASS] _pdf_dir_for_resend cai para pasta monitorada/PDF como ultimo recurso")


def test_convert_keeps_original_and_pdf() -> None:
    # Ramo nao-PDF: a pasta PDF deve conter o ORIGINAL + o PDF convertido.
    # Monkeypatch do conversor (sem Office/LibreOffice neste ambiente).
    original = pu.convert_file_to_pdf

    def fake_convert(src: str, outdir: str, log) -> str:
        out = Path(outdir) / f"{Path(src).stem}.pdf"
        out.write_bytes(b"%PDF-1.4 fake\n")
        return str(out)

    pu.convert_file_to_pdf = fake_convert
    try:
        tmp = Path(tempfile.mkdtemp(prefix="pdf_resend_"))
        src = tmp / "lote_001" / "documento.docx"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("conteudo")
        pdf_dir = tmp / "PDF"
        out = pu.convert_to_pdf_in_folder(str(src), str(pdf_dir), _log)
        names = sorted(p.name for p in pdf_dir.iterdir())
        assert names == ["documento.docx", "documento.pdf"], f"esperava original + pdf, veio {names}"
        assert _norm(out).endswith("PDF/documento.pdf"), out
        assert src.exists(), "o original deve permanecer tambem no local de origem"
        print("[PASS] convert_to_pdf_in_folder mantem original + PDF na pasta")
    finally:
        pu.convert_file_to_pdf = original


if __name__ == "__main__":
    test_resend_dir_uses_staging_run_dir()
    test_resend_dir_fallback_from_temp_path()
    test_resend_dir_last_resort_folder()
    test_convert_keeps_original_and_pdf()
    print("\nTODOS OS TESTES DO FLUXO DE REENVIO PDF PASSARAM.")
