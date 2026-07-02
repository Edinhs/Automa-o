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


def test_resend_splits_into_batches() -> None:
    # Reenvio de PDF agora vai EM LOTES: 5 arquivos com batch_size=2 -> 3 lotes (2, 2, 1),
    # cada um em sua subpasta 'lote_NNN' e com batch_number distinto, de modo que o
    # batches_for_upload do upload enxergue 3 lotes separados (checkpoint por lote).
    import app.cli.local_agent as la  # noqa: E402

    def fake_convert(source: str, pdf_dir: str, log) -> str:
        Path(pdf_dir).mkdir(parents=True, exist_ok=True)
        out = Path(pdf_dir) / f"{Path(source).stem}.pdf"
        out.write_bytes(b"%PDF-1.4 fake\n")
        return str(out)

    orig_convert = la.convert_to_pdf_in_folder
    orig_update = la.update_file
    la.convert_to_pdf_in_folder = fake_convert
    la.update_file = lambda *_a, **_k: None
    try:
        tmp = Path(tempfile.mkdtemp(prefix="pdf_batch_"))
        pdf_dir = str(tmp / "PDF")
        items = [
            {
                "file_id": i,
                "file_name": f"doc{i}.docx",
                "temp_path": str(tmp / f"doc{i}.docx"),
                "original_path": str(tmp / f"doc{i}.docx"),
            }
            for i in range(1, 6)  # 5 arquivos
        ]
        resend_files, resent, failed = la._build_resend_batch(None, items, pdf_dir, _log, batch_size=2)
        assert len(resend_files) == 5 and not failed, (resend_files, failed)
        assert sorted({f["batch_number"] for f in resend_files}) == [1, 2, 3]
        folders = {f["batch_number"]: _norm(f["batch_folder_path"]) for f in resend_files}
        assert folders[1].endswith("PDF/lote_001"), folders[1]
        assert folders[2].endswith("PDF/lote_002"), folders[2]
        assert folders[3].endswith("PDF/lote_003"), folders[3]
        # O agrupador do upload deve enxergar 3 lotes distintos (2, 2, 1).
        groups = pu.batches_for_upload(resend_files, 2)
        assert sorted(len(g) for g in groups) == [1, 2, 2], [len(g) for g in groups]
        print("[PASS] _build_resend_batch divide o reenvio em lotes (lote_NNN) -> 3 lotes")
    finally:
        la.convert_to_pdf_in_folder = orig_convert
        la.update_file = orig_update


if __name__ == "__main__":
    test_resend_dir_uses_staging_run_dir()
    test_resend_dir_fallback_from_temp_path()
    test_resend_dir_last_resort_folder()
    test_convert_keeps_original_and_pdf()
    test_resend_splits_into_batches()
    print("\nTODOS OS TESTES DO FLUXO DE REENVIO PDF PASSARAM.")
