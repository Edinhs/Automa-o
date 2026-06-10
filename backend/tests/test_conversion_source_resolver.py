"""Regressao: o reenvio pos-monitoramento deve achar o arquivo mesmo quando o temp_path sumiu.

Bug observado: convert_to_pdf_in_folder RECORTA (shutil.move) o arquivo de lote_XXX/ para a pasta
PDF/ na RAIZ do staging. Num ciclo/retry seguinte, o codigo procurava o original em lote_XXX/ (ou
em lote_XXX/PDF/, lugar errado) e falhava com "Arquivo nao encontrado para conversao". O resolvedor
_existing_conversion_source tolera isso achando o PDF ja convertido/recortado na raiz do staging,
o pdf_path do item, ou o original preservado na pasta monitorada — nesta ordem, sem mover nada.
"""

from app.cli.local_agent import _existing_conversion_source


def _staging(tmp_path):
    root = tmp_path / "SPEC_341_20260608_195323"
    lote = root / "lote_002"
    pdf = root / "PDF"
    lote.mkdir(parents=True)
    pdf.mkdir(parents=True)
    return root, lote, pdf


def test_resolve_prefere_temp_path_quando_existe(tmp_path):
    root, lote, _pdf = _staging(tmp_path)
    temp = lote / "X1H_SSTS_Headlamp.docx"
    temp.write_text("doc", encoding="utf-8")
    item = {"temp_path": str(temp)}

    assert _existing_conversion_source(item, str(root)) == str(temp)


def test_resolve_acha_pdf_ja_convertido_na_raiz_do_staging(tmp_path):
    root, lote, pdf = _staging(tmp_path)
    temp = lote / "X1H_SSTS_Headlamp.docx"  # foi recortado e convertido -> nao existe mais aqui
    converted = pdf / "X1H_SSTS_Headlamp.pdf"
    converted.write_text("%PDF-1.4", encoding="utf-8")
    item = {"temp_path": str(temp)}

    # temp_folder_path None: tem que derivar a raiz do PDF a partir do avo do temp_path (lote -> root).
    assert _existing_conversion_source(item, None) == str(converted)


def test_resolve_acha_arquivo_recortado_ainda_nao_convertido(tmp_path):
    root, lote, pdf = _staging(tmp_path)
    temp = lote / "VFS_FCLU_5A_P341.doc"
    moved = pdf / "VFS_FCLU_5A_P341.doc"
    moved.write_text("doc movido", encoding="utf-8")
    item = {"temp_path": str(temp)}

    assert _existing_conversion_source(item, str(root)) == str(moved)


def test_resolve_cai_para_original_preservado(tmp_path):
    root, lote, _pdf = _staging(tmp_path)
    temp = lote / "spec.docx"  # nao existe
    original = tmp_path / "monitorada" / "spec.docx"
    original.parent.mkdir(parents=True)
    original.write_text("original", encoding="utf-8")
    item = {"temp_path": str(temp), "original_path": str(original)}

    assert _existing_conversion_source(item, str(root)) == str(original)


def test_resolve_retorna_none_quando_nada_existe(tmp_path):
    root, lote, _pdf = _staging(tmp_path)
    item = {"temp_path": str(lote / "sumiu.docx"), "original_path": str(tmp_path / "tambem_sumiu.docx")}

    assert _existing_conversion_source(item, str(root)) is None
