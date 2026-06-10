"""Regressao: click_first/fill_first NUNCA podem clicar/preencher um elemento DESABILITADO.

Cobre o bug onde o helper generico resolvia no primeiro elemento VISIVEL sem checar is_enabled:
o submit "Upload Files" (visivel, mas disabled ate um arquivo ser anexado) era escolhido e o
.click() do Playwright estourava `Timeout ... element is not enabled`. Agora first_visible, quando
require_enabled=True (default de click_first/fill_first), varre os matches e pula os desabilitados.

Os testes usam dublês simples (sem navegador) que imitam a API minima que first_visible consome:
o locator expoe count()/nth()/first; o elemento expoe is_visible()/is_enabled()/click()/fill().
"""

from app.services.playwright.browser import click_first, fill_first, first_visible


class FakeElement:
    def __init__(self, visible: bool = True, enabled: bool = True, present: bool = True):
        self._visible = visible
        self._enabled = enabled
        self._present = present
        self.clicks = 0
        self.fills: list[str] = []

    def count(self):  # usado pelo caminho require_enabled=False (locator.first.count())
        return 1 if self._present else 0

    def is_visible(self, timeout=None):  # noqa: ARG002 - assina igual ao Playwright
        return self._visible

    def is_enabled(self, timeout=None):  # noqa: ARG002
        return self._enabled

    def click(self, timeout=None):  # noqa: ARG002
        if not self._enabled:
            raise TimeoutError("Locator.click: Timeout exceeded - element is not enabled")
        self.clicks += 1

    def fill(self, value, timeout=None):  # noqa: ARG002
        if not self._enabled:
            raise TimeoutError("Locator.fill: Timeout exceeded - element is not enabled")
        self.fills.append(value)


class FakeLocator:
    def __init__(self, elements: list[FakeElement]):
        self._elements = elements

    def count(self):
        return len(self._elements)

    def nth(self, index: int):
        return self._elements[index]

    @property
    def first(self):
        return self._elements[0] if self._elements else FakeElement(present=False)


def test_click_first_pula_desabilitado_e_clica_habilitado():
    disabled = FakeElement(visible=True, enabled=False)  # ex.: submit "Upload Files" antes de anexar
    enabled = FakeElement(visible=True, enabled=True)
    locator = FakeLocator([disabled, enabled])

    assert click_first([lambda: locator]) is True
    assert enabled.clicks == 1
    assert disabled.clicks == 0


def test_click_first_retorna_false_quando_todos_desabilitados():
    d1 = FakeElement(enabled=False)
    d2 = FakeElement(enabled=False)
    locator = FakeLocator([d1, d2])

    assert click_first([lambda: locator]) is False
    assert d1.clicks == 0 and d2.clicks == 0


def test_click_first_atravessa_factories_ate_achar_habilitado():
    disabled = FakeElement(enabled=False)
    enabled = FakeElement(enabled=True)
    loc_disabled = FakeLocator([disabled])
    loc_enabled = FakeLocator([enabled])

    assert click_first([lambda: loc_disabled, lambda: loc_enabled]) is True
    assert enabled.clicks == 1
    assert disabled.clicks == 0


def test_click_first_ignora_invisivel_mesmo_habilitado():
    invisible = FakeElement(visible=False, enabled=True)
    visible = FakeElement(visible=True, enabled=True)
    locator = FakeLocator([invisible, visible])

    assert click_first([lambda: locator]) is True
    assert visible.clicks == 1
    assert invisible.clicks == 0


def test_fill_first_pula_input_desabilitado():
    disabled = FakeElement(enabled=False)
    enabled = FakeElement(enabled=True)
    locator = FakeLocator([disabled, enabled])

    assert fill_first([lambda: locator], "valor") is True
    assert enabled.fills == ["valor"]
    assert disabled.fills == []


def test_first_visible_sem_require_enabled_preserva_deteccao():
    # Caminho de deteccao (require_enabled=False, default de first_visible): retorna o 1o VISIVEL
    # mesmo desabilitado — comportamento original, usado para presenca/visibilidade, nao para clicar.
    disabled = FakeElement(visible=True, enabled=False)
    locator = FakeLocator([disabled])

    assert first_visible([lambda: locator]) is disabled


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
