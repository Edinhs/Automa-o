"""Regressao: o monitor deve casar o arquivo pela coluna Name EXATA e NUNCA classificar como
deletavel um nome que tenha alguma linha Ready.

Bug observado: leitura de status por SUBSTRING (`name in row_text`) com `break` no 1o match fazia
um arquivo herdar o status da linha errada quando havia nomes colidentes/duplicados (ex.: o original
'.doc' em Error e o PDF convertido '.pdf' em Ready compartilhando o nome-base, ou duplicatas do
reenvio duplo) — e o Ready acabava deletado. Agora: match exato da coluna Name + varredura de TODAS
as linhas + preferencia por Ready.

Dublê de 'page': `evaluate` devolve as linhas estruturadas (como read_structured_file_rows espera) e
`locator` devolve um body vazio (page_text -> "").
"""

from app.services.playwright.playground_monitor import read_file_statuses


class _FakeBodyLocator:
    def count(self):
        return 0

    def inner_text(self, timeout=None):  # usado por page_text(page) -> body
        return ""

    def nth(self, index):  # nao deve ser chamado (count == 0)
        raise IndexError


class _FakePage:
    def __init__(self, structured_rows):
        self._rows = structured_rows

    def evaluate(self, _js):  # read_structured_file_rows(page)
        return self._rows

    def locator(self, _selector):
        return _FakeBodyLocator()


def _row(name: str, status: str) -> dict:
    headers = ["Name", "Status", "Upload date", "Size"]
    cells = [name, status, "08/06/2026, 21:12", "30 KB"]
    return {"source": "table", "headers": headers, "cells": cells, "text": f"{name} {status} 08/06/2026, 21:12 30 KB"}


def test_pdf_ready_nao_herda_error_do_doc_colidente():
    rows = [_row("~$71_CTS_SWS_200612_03.doc", "Error"), _row("~$71_CTS_SWS_200612_03.pdf", "Ready")]
    statuses = read_file_statuses(_FakePage(rows), ["~$71_CTS_SWS_200612_03.doc", "~$71_CTS_SWS_200612_03.pdf"])
    assert statuses["~$71_CTS_SWS_200612_03.pdf"]["status"] == "Ready"
    assert statuses["~$71_CTS_SWS_200612_03.doc"]["status"] == "Error"


def test_duplicatas_mesmo_nome_preferem_ready():
    # Duas linhas com o MESMO nome (caso do reenvio duplicado): uma Error, uma Ready -> Ready vence,
    # logo o nome NAO entra em 'deletable'.
    rows = [_row("report.pdf", "Error"), _row("report.pdf", "Ready")]
    statuses = read_file_statuses(_FakePage(rows), ["report.pdf"])
    assert statuses["report.pdf"]["status"] == "Ready"


def test_match_exato_nao_pega_arquivo_de_nome_maior():
    # 'A.docx' (Error) e substring de 'XA.docx' (Ready). Com match exato, 'A.docx' resolve Error
    # (nao pode ser mascarado como Ready pelo XA.docx) e seria corretamente tratado.
    rows = [_row("XA.docx", "Ready"), _row("A.docx", "Error")]
    statuses = read_file_statuses(_FakePage(rows), ["A.docx"])
    assert statuses["A.docx"]["status"] == "Error"


def test_nome_ausente_e_notfound():
    rows = [_row("outro.docx", "Ready")]
    statuses = read_file_statuses(_FakePage(rows), ["sumiu.docx"])
    assert statuses["sumiu.docx"]["status"] == "NotFound"
