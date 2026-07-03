r"""
test_pdf_recovery.py -- Testes deterministicos (sem Office real) da RECUPERACAO de
arquivos corrompidos na conversao para PDF:

  1. convert_file_to_pdf tenta o Office em modo NORMAL e, se falhar, reabre em modo
     RECUPERACAO (Word OpenAndRepair / Excel CorruptLoad) ANTES de cair no LibreOffice.
  2. Quando nem o reparo nem o LibreOffice resolvem, levanta ManualReviewRequired
     (comportamento preservado).
  3. O script PowerShell contem os branches de reparo (HUB_REPAIR/OpenAndRepair/CorruptLoad).

Uso: a partir de backend/  ->  .venv\Scripts\python.exe scripts\test_pdf_recovery.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import app.services.playwright.playground_upload as pu  # noqa: E402
from app.services.playwright.errors import ManualReviewRequired  # noqa: E402


def _log(*_a, **_k) -> None:
    pass


def test_recovery_retry_then_success() -> None:
    """Normal falha -> reparo (repair=True) gera o PDF -> LibreOffice NAO e chamado."""
    calls: list[bool] = []
    orig_com = pu.convert_office_via_com
    orig_soffice = pu.find_soffice

    def fake_com(source, target_pdf, log, repair: bool = False) -> bool:
        calls.append(repair)
        if repair:
            Path(target_pdf).write_bytes(b"%PDF-1.4 recuperado\n")
            return True
        return False  # modo normal falha (arquivo "corrompido")

    def fail_if_soffice():
        raise AssertionError("LibreOffice nao deveria ser chamado quando o reparo resolve.")

    pu.convert_office_via_com = fake_com
    pu.find_soffice = fail_if_soffice
    try:
        tmp = Path(tempfile.mkdtemp(prefix="pdf_recovery_"))
        src = tmp / "corrompido.docx"
        src.write_text("conteudo")
        out = pu.convert_file_to_pdf(str(src), str(tmp / "PDF"), _log)
        assert Path(out).exists() and out.lower().endswith(".pdf"), out
        assert calls == [False, True], f"esperava [normal, reparo], veio {calls}"
        print("[PASS] convert_file_to_pdf recupera via Office (reparo) antes do LibreOffice")
    finally:
        pu.convert_office_via_com = orig_com
        pu.find_soffice = orig_soffice


def test_unrecoverable_goes_to_manual_review() -> None:
    """COM normal e reparo falham e nao ha LibreOffice -> ManualReviewRequired."""
    orig_com = pu.convert_office_via_com
    orig_soffice = pu.find_soffice

    pu.convert_office_via_com = lambda *a, **k: False
    pu.find_soffice = lambda: None
    try:
        tmp = Path(tempfile.mkdtemp(prefix="pdf_recovery_"))
        src = tmp / "irrecuperavel.docx"
        src.write_text("conteudo")
        raised = False
        try:
            pu.convert_file_to_pdf(str(src), str(tmp / "PDF"), _log)
        except ManualReviewRequired:
            raised = True
        assert raised, "esperava ManualReviewRequired quando reparo e LibreOffice falham."
        print("[PASS] sem recuperacao possivel -> ManualReviewRequired (preservado)")
    finally:
        pu.convert_office_via_com = orig_com
        pu.find_soffice = orig_soffice


def test_ps_script_has_repair_branches() -> None:
    script = pu._OFFICE_COM_PS_SCRIPT
    for token in ("HUB_REPAIR", "OpenAndRepair", "CorruptLoad"):
        assert token in script, f"branch de reparo ausente no script: {token}"
    print("[PASS] _OFFICE_COM_PS_SCRIPT contem HUB_REPAIR / OpenAndRepair / CorruptLoad")


if __name__ == "__main__":
    test_recovery_retry_then_success()
    test_unrecoverable_goes_to_manual_review()
    test_ps_script_has_repair_branches()
    print("\nTODOS OS TESTES DE RECUPERACAO DE PDF PASSARAM.")
