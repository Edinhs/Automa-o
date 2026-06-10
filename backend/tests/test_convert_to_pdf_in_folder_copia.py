"""Regressao: convert_to_pdf_in_folder deve COPIAR (nao recortar) o arquivo de origem.

Mudanca: a funcao usava shutil.move (recortar) -> agora usa shutil.copy2 (copiar). O arquivo
de origem deve continuar existindo no local original apos a conversao.

Os testes mockam convert_file_to_pdf para nao depender do LibreOffice instalado.
"""

from pathlib import Path
from unittest.mock import patch

from app.services.playwright.playground_upload import convert_to_pdf_in_folder


def _fake_log(level, message, **kwargs):
    pass


def _fake_convert_file_to_pdf(source_path: str, dest_dir: str, log) -> str:
    """Simula conversao: retorna um path .pdf baseado no source."""
    stem = Path(source_path).stem
    dest = Path(dest_dir) / f"{stem}.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"%PDF-1.4")
    return str(dest)


def test_origem_permanece_apos_copia(tmp_path):
    """O arquivo de origem NAO deve desaparecer apos convert_to_pdf_in_folder."""
    source = tmp_path / "lote_001" / "spec.docx"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("conteudo real", encoding="utf-8")

    pdf_dir = str(tmp_path / "PDF")

    with patch(
        "app.services.playwright.playground_upload.convert_file_to_pdf",
        side_effect=_fake_convert_file_to_pdf,
    ):
        convert_to_pdf_in_folder(str(source), pdf_dir, _fake_log)

    # Origem ainda existe (foi COPIADA, nao movida).
    assert source.exists(), "A origem deve continuar existindo apos a copia."


def test_copia_cria_arquivo_na_pasta_pdf(tmp_path):
    """O arquivo deve aparecer na pasta PDF de destino apos a copia."""
    source = tmp_path / "lote_001" / "relatorio.docx"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("relatorio", encoding="utf-8")

    pdf_dir = str(tmp_path / "PDF")

    with patch(
        "app.services.playwright.playground_upload.convert_file_to_pdf",
        side_effect=_fake_convert_file_to_pdf,
    ):
        pdf_path = convert_to_pdf_in_folder(str(source), pdf_dir, _fake_log)

    assert Path(pdf_path).exists(), "O PDF convertido deve existir na pasta de destino."
    assert Path(pdf_path).suffix.lower() == ".pdf"


def test_colisao_de_nome_renomeia_com_timestamp(tmp_path):
    """Se um arquivo de mesmo nome ja existe no destino, deve ser renomeado (nao sobrescrito)."""
    source = tmp_path / "lote_001" / "spec.docx"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("conteudo v2", encoding="utf-8")

    pdf_dir = tmp_path / "PDF"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    # Pre-existente com o mesmo nome na pasta de destino.
    existing = pdf_dir / "spec.docx"
    existing.write_text("conteudo v1", encoding="utf-8")

    with patch(
        "app.services.playwright.playground_upload.convert_file_to_pdf",
        side_effect=_fake_convert_file_to_pdf,
    ):
        convert_to_pdf_in_folder(str(source), str(pdf_dir), _fake_log)

    # O original do destino nao deve ter sido sobrescrito.
    assert existing.exists(), "O arquivo pre-existente no destino deve permanecer."
    assert existing.read_text(encoding="utf-8") == "conteudo v1", "O pre-existente nao pode ser sobrescrito."
    # A origem ainda existe.
    assert source.exists(), "A origem deve continuar existindo apos a copia."


def test_arquivo_ja_no_destino_nao_copia_novamente(tmp_path):
    """Se source.resolve() == destino.resolve(), nao deve copiar (evita copiar sobre si mesmo)."""
    pdf_dir = tmp_path / "PDF"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    source = pdf_dir / "ja_convertido.docx"
    source.write_text("conteudo", encoding="utf-8")

    with patch(
        "app.services.playwright.playground_upload.convert_file_to_pdf",
        side_effect=_fake_convert_file_to_pdf,
    ):
        pdf_path = convert_to_pdf_in_folder(str(source), str(pdf_dir), _fake_log)

    # O arquivo de origem continua existindo (nenhuma excecao foi lancada).
    assert source.exists()
    assert Path(pdf_path).exists()
