r"""
test_pdf_reprocess.py -- Testes deterministicos (sem navegador) do reprocesso PDF:
  1. _pdf_dir_for_reprocess: pasta 'PDF' fora do temp (folder_path) + fallbacks.
  2. convert_to_pdf_in_folder (ramo .pdf): deixa SOMENTE o PDF na pasta, sem copiar original.

Uso: a partir do diretorio backend/  ->  .venv\Scripts\python.exe scripts\test_pdf_reprocess.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.cli.local_agent import _pdf_dir_for_reprocess  # noqa: E402
from app.services.playwright.playground_upload import convert_to_pdf_in_folder  # noqa: E402


def _log(*_a, **_k) -> None:
    pass


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def test_pdf_dir_helper() -> None:
    # folder_path (pasta monitorada) -> <folder>/PDF
    d = _pdf_dir_for_reprocess("C:/mon")
    assert d and _norm(d).endswith("/PDF") and "mon" in _norm(d), d
    # fallback: parent do arquivo de origem
    d = _pdf_dir_for_reprocess(None, "C:/mon/sub/file.docx")
    assert d and _norm(d).endswith("mon/sub/PDF"), d
    # ultimo recurso: temp
    d = _pdf_dir_for_reprocess(None, None, "C:/tmp")
    assert d and _norm(d).endswith("tmp/PDF"), d
    # sem base -> None
    assert _pdf_dir_for_reprocess(None) is None
    print("[PASS] _pdf_dir_for_reprocess (folder_path + fallbacks)")


def test_convert_pdf_branch_keeps_only_pdf() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="pdf_reproc_"))
    src = tmp / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 conteudo de teste\n")
    pdf_dir = tmp / "PDF"
    out = convert_to_pdf_in_folder(str(src), str(pdf_dir), _log)
    in_pdf = sorted(p.name for p in pdf_dir.iterdir())
    assert in_pdf == ["doc.pdf"], f"esperava so doc.pdf na pasta PDF, veio {in_pdf}"
    assert Path(out).parent.resolve() == pdf_dir.resolve(), out
    assert src.exists(), "o original deve permanecer no local de origem"
    # Segunda origem .pdf com MESMO nome -> guarda de colisao (nao sobrescreve)
    src2 = tmp / "sub_doc.pdf"
    src2.write_bytes(b"%PDF-1.4 outro\n")
    # renomeia para colidir com doc.pdf de proposito
    collide = tmp / "doc2.pdf"
    collide.write_bytes(b"%PDF-1.4 colisao\n")
    # forca colisao: copia como 'doc.pdf' de outra origem
    import os
    src3_dir = Path(tempfile.mkdtemp(prefix="src3_"))
    src3 = src3_dir / "doc.pdf"
    src3.write_bytes(b"%PDF-1.4 origem distinta\n")
    out2 = convert_to_pdf_in_folder(str(src3), str(pdf_dir), _log)
    in_pdf2 = sorted(p.name for p in pdf_dir.iterdir())
    assert len(in_pdf2) == 2, f"colisao deveria gerar 2 PDFs distintos, veio {in_pdf2}"
    assert all(n.lower().endswith(".pdf") for n in in_pdf2), in_pdf2
    print("[PASS] convert_to_pdf_in_folder ramo .pdf (so PDF na pasta + colisao)")


if __name__ == "__main__":
    test_pdf_dir_helper()
    test_convert_pdf_branch_keeps_only_pdf()
    print("\nTODOS OS TESTES DE REPROCESSO PDF PASSARAM.")
