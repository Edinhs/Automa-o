"""Regressao: a exclusao de arquivos nao-Ready do workspace deve ser cirurgica.

Cobre o bug onde a automacao apagava SEMPRE a primeira linha da tabela (match por
substring em find_file_row) e/ou apagava arquivos Ready. Garante:

1. find_file_row casa a linha pela coluna Name EXATA (e nao a primeira que contem o texto).
2. find_file_row retorna None quando ha ambiguidade (varias candidatas, nenhuma exata).
3. live_row_status le e normaliza o status DA PROPRIA linha (base da trava anti-Ready).

Os testes usam dublês simples (sem navegador): a 'row' expoe .evaluate()/.is_visible() e
o 'page' expoe .locator(...).filter(has_text=...).first/.count()/.nth(), imitando a API
minima do Playwright que find_file_row consome.
"""

from app.services.playwright.playground_monitor import find_file_row, live_row_status


class FakeFirst:
    def wait_for(self, **_kwargs):
        return None


class FakeRow:
    def __init__(self, name: str, status: str, text: str | None = None, visible: bool = True):
        self._data = {
            "name": name,
            "status": status,
            "text": text if text is not None else f"{name} {status}".strip(),
        }
        self._visible = visible

    def evaluate(self, _js: str):
        return dict(self._data)

    def is_visible(self, timeout=None):  # noqa: ARG002 - assina igual ao Playwright
        return self._visible


class FakeLocator:
    def __init__(self, rows: list[FakeRow]):
        self._rows = rows

    def filter(self, has_text=None):
        if has_text is None:
            return self
        return FakeLocator([r for r in self._rows if has_text in r._data["text"]])

    @property
    def first(self):
        if not self._rows:
            raise RuntimeError("locator vazio")
        return FakeFirst()

    def count(self):
        return len(self._rows)

    def nth(self, index: int):
        return self._rows[index]


class FakePage:
    """So a 'table tbody tr' tem linhas; '[role=row]' fica vazio (como na UI real aqui)."""

    def __init__(self, rows: list[FakeRow]):
        self._rows = rows

    def locator(self, selector: str):
        return FakeLocator(list(self._rows)) if selector == "table tbody tr" else FakeLocator([])


def test_find_file_row_prefere_nome_exato_em_vez_da_primeira_linha():
    # "a_report.doc" (Error) aparece ANTES e seu texto CONTEM "report.doc";
    # o codigo antigo retornaria essa primeira linha por engano.
    ready = FakeRow("report.doc", "Ready")
    rows = [FakeRow("a_report.doc", "Error"), ready]
    page = FakePage(rows)

    found = find_file_row(page, "report.doc")

    assert found is ready
    assert live_row_status(found) == "Ready"


def test_find_file_row_localiza_o_arquivo_com_erro_correto():
    error = FakeRow("341_ITS_windshield_wiper_rev01.doc", "Error")
    rows = [FakeRow("CTS-EE-SAS_P3410_V0_R0.docx", "Ready"), error]
    page = FakePage(rows)

    found = find_file_row(page, "341_ITS_windshield_wiper_rev01.doc")

    assert found is error
    assert live_row_status(found) == "Error"


def test_find_file_row_retorna_none_quando_ambiguo_sem_match_exato():
    # Duas candidatas contem "report.doc", mas NENHUMA se chama exatamente assim:
    # nao adivinha -> retorna None (nao apaga a linha errada).
    rows = [FakeRow("a_report.doc", "Error"), FakeRow("b_report.doc", "Error")]
    page = FakePage(rows)

    assert find_file_row(page, "report.doc") is None


def test_find_file_row_fallback_candidata_unica():
    # Nome da celula vem vazio (parsing falho), mas o filtro deixou UMA candidata: usa ela.
    row = FakeRow(name="", status="Error", text="weird.doc Error")
    page = FakePage([row])

    assert find_file_row(page, "weird.doc") is row


def test_live_row_status_normaliza_status_da_linha():
    assert live_row_status(FakeRow("x.doc", "Ready")) == "Ready"
    assert live_row_status(FakeRow("x.doc", "Erro")) == "Error"  # PT-BR
    assert live_row_status(FakeRow("x.doc", "Processing")) == "Processing"
    assert live_row_status(FakeRow("x.doc", "Pending")) == "Pending"
    # Status vazio cai no texto da linha como fallback.
    assert live_row_status(FakeRow("x.doc", "", text="x.doc Ready")) == "Ready"


def test_live_row_status_usa_coluna_status_e_ignora_nome():
    # Nome contem a palavra 'error' mas o status real e Ready: nao pode virar Error.
    row = FakeRow(name="error_handling_guide.doc", status="Ready", text="error_handling_guide.doc Ready")
    assert live_row_status(row) == "Ready"


if __name__ == "__main__":
    # Executavel sem pytest (release sanitizado nao traz pytest): roda todos os test_*.
    import traceback

    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"PASS {_name}")
            except Exception:  # noqa: BLE001
                failures += 1
                print(f"FAIL {_name}")
                traceback.print_exc()
    print(f"\n{'OK' if not failures else f'{failures} FALHA(S)'}")
    raise SystemExit(1 if failures else 0)
