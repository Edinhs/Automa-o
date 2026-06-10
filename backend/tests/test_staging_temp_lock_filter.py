"""Regressao: arquivos temporarios/bloqueio do Office (~$nome.docx) NAO devem ser ingeridos.

Esses owner files do MS Office tem extensao valida (.doc/.docx/...) e por isso passavam pelo
filtro de extensao do scan, eram enviados ao Playground (davam Error, 162 bytes) e sumiam entre
ciclos de monitor (o Office os apaga ao fechar o documento). Agora sao filtrados na origem.
"""

from app.services.automation_staging import (
    DEFAULT_UPLOAD_EXTENSIONS,
    is_temp_or_lock_file,
    scan_monitored_folder,
)


def test_is_temp_or_lock_file():
    assert is_temp_or_lock_file("~$S_BCM_2A_P341.doc") is True
    assert is_temp_or_lock_file("~$mponentClassification IPC_P3410_Ed2_R2.docx") is True
    assert is_temp_or_lock_file(".~lock.report.docx#") is True
    # Documentos reais nao podem ser confundidos.
    assert is_temp_or_lock_file("report.docx") is False
    assert is_temp_or_lock_file("X1H_SSTS_Headlamp.docx") is False
    assert is_temp_or_lock_file("budget~final.xlsx") is False  # '~' no meio nao e owner file


def test_scan_ignora_owner_files_do_office(tmp_path):
    (tmp_path / "report.docx").write_text("doc real", encoding="utf-8")
    (tmp_path / "~$report.docx").write_text("owner", encoding="utf-8")          # lock do Office
    (tmp_path / ".~lock.report.docx#").write_text("lock", encoding="utf-8")     # lock do LibreOffice
    (tmp_path / "notes.xyz").write_text("ext nao suportada", encoding="utf-8")  # ignorado por extensao

    files, stats = scan_monitored_folder(tmp_path, set(DEFAULT_UPLOAD_EXTENSIONS))

    names = sorted(p.name for p in files)
    assert names == ["report.docx"]
    assert stats["temp_lock_skipped"] == 2
    assert stats["matched_files"] == 1


def test_scan_em_subpastas_tambem_filtra(tmp_path):
    lote = tmp_path / "lote_001"
    lote.mkdir()
    (lote / "spec.doc").write_text("real", encoding="utf-8")
    (lote / "~$spec.doc").write_text("owner", encoding="utf-8")

    files, stats = scan_monitored_folder(tmp_path, set(DEFAULT_UPLOAD_EXTENSIONS))

    assert sorted(p.name for p in files) == ["spec.doc"]
    assert stats["temp_lock_skipped"] == 1
