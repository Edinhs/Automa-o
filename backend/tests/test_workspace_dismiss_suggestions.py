"""Regressao: o dropdown de autosuggest do Filter Workspace intercepta o clique no link.

Cobre o bug onde, apos pesquisar o workspace, o Cloudscape mantinha aberto o dropdown de
sugestoes (role="option", com awsui_filtering-match-highlight) sobre o link da listagem. O
`<a>` resolvia visivel/habilitado/estavel, mas o overlay "subtree intercepts pointer events"
e o `.click()` estourava o Timeout 4000ms. `dismiss_filter_suggestions` pressiona Escape (que
fecha o dropdown sem limpar o filtro) e so retorna quando os role="option" somem.

Os testes usam dubles simples (sem navegador): a page expoe locator()/keyboard.press(); o
locator expoe count(). O contador de options cai para 0 quando "Escape" e pressionado,
imitando o fechamento do dropdown do Cloudscape.
"""

from app.services.playwright.playground_workspace import dismiss_filter_suggestions


class FakeLocator:
    def __init__(self, page):
        self._page = page

    def count(self):
        return 0 if self._page.dropdown_closed else self._page.option_count


class FakeKeyboard:
    def __init__(self, page):
        self._page = page
        self.presses: list[str] = []

    def press(self, key):
        self.presses.append(key)
        if key == "Escape" and self._page.escape_closes:
            self._page.dropdown_closed = True


class FakePage:
    def __init__(self, option_count: int, *, escape_closes: bool = True):
        self.option_count = option_count
        self.dropdown_closed = option_count == 0
        self.escape_closes = escape_closes
        self.keyboard = FakeKeyboard(self)

    def locator(self, selector):  # noqa: ARG002 - assina igual ao Playwright
        return FakeLocator(self)


def test_dismiss_pressiona_escape_e_fecha_dropdown():
    page = FakePage(option_count=3)

    dismiss_filter_suggestions(page, timeout_ms=500)

    assert page.keyboard.presses == ["Escape"]
    assert page.dropdown_closed is True


def test_dismiss_sem_options_nao_pressiona_nada():
    # Sem dropdown aberto (caminho por URL direta ja navegou): nao deve mexer no teclado.
    page = FakePage(option_count=0)

    dismiss_filter_suggestions(page, timeout_ms=500)

    assert page.keyboard.presses == []


def test_dismiss_retorna_no_timeout_quando_dropdown_persiste():
    # Escape nao fecha o overlay: a funcao tenta uma vez e retorna no deadline, sem travar.
    page = FakePage(option_count=2, escape_closes=False)

    dismiss_filter_suggestions(page, timeout_ms=100)

    assert page.keyboard.presses == ["Escape"]
    assert page.dropdown_closed is False


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
