r"""
test_upload_no_duplicate.py -- Testes deterministicos (sem navegador) da protecao
ANTI-DUPLICACAO no upload:

Quando um lote "nao confirma" no tempo (falso negativo da confirmacao estrita), a automacao
agora VERIFICA na workspace (F5) quais arquivos ja estao la e so reenvia/isola os REALMENTE
ausentes -- evitando o envio em duplicidade (lote + um-a-um) relatado.

Cenarios cobertos:
  1. Todos ja presentes      -> handle_uploading_error NAO e chamado; nada e reenviado.
  2. Parte presente/ausente  -> handle_uploading_error e chamado SO com os ausentes.
  3. Nenhum presente         -> handle_uploading_error e chamado com o lote inteiro (igual a hoje).
  4. Verificacao falha        -> fallback: trata o lote como ausente (comportamento atual).

Uso: a partir de backend/  ->  .venv\Scripts\python.exe scripts\test_upload_no_duplicate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import app.services.playwright.playground_upload as pu  # noqa: E402
from app.services.playwright.errors import UploadFailed  # noqa: E402


def _log(*_a, **_k) -> None:
    pass


class _FakePage:
    pass


class _FakeBrowser:
    def __init__(self):
        self.page = _FakePage()
        self.session_dir = "fake"


def _batch(n: int) -> list[dict]:
    return [{"file_id": i, "file_name": f"f{i}.pdf", "path": f"C:/tmp/PDF/f{i}.pdf"} for i in range(1, n + 1)]


def _run_loop(present_absent):
    """Dirige upload_files_to_workspace com stubs; retorna (result, handle_calls)."""
    handle_calls: list[list[dict]] = []
    saved = {name: getattr(pu, name) for name in (
        "open_upload_browser_session", "upload_batch", "verify_batch_present_in_workspace",
        "handle_uploading_error", "recover_upload_area_in_same_session",
        "save_recovery_screenshot", "close_browser",
    )}

    def fake_open_session(*_a, **_k):
        return _FakeBrowser(), _FakePage()

    def fake_upload_batch(page, batch, log, **_k):
        raise UploadFailed("Lote nao confirmado como enviado em 60s: rede=sem resposta 2xx.")

    def fake_verify(page, payload, workspace_name, batch, log, should_continue=None):
        return present_absent(batch)

    def fake_handle(page, absent, batch_number, *a, **k):
        handle_calls.append(list(absent))
        return pu.uploaded_results(absent)  # simula isolamento/reenvio bem-sucedido dos ausentes

    pu.open_upload_browser_session = fake_open_session
    pu.upload_batch = fake_upload_batch
    pu.verify_batch_present_in_workspace = fake_verify
    pu.handle_uploading_error = fake_handle
    pu.recover_upload_area_in_same_session = lambda *a, **k: None
    pu.save_recovery_screenshot = lambda *a, **k: False
    pu.close_browser = lambda *a, **k: None
    try:
        payload = {"workspace_name": "WS", "files": _batch(3), "batch_size": 5}
        result = pu.upload_files_to_workspace(task_id=1, user_id=1, payload=payload, log=_log)
        return result, handle_calls
    finally:
        for name, fn in saved.items():
            setattr(pu, name, fn)


def _names(items):
    return sorted(i.get("file_name") for i in items)


def test_all_present_no_resend() -> None:
    result, handle_calls = _run_loop(lambda batch: (list(batch), []))
    assert handle_calls == [], f"handle_uploading_error nao deveria ser chamado; veio {handle_calls}"
    assert _names(result["uploaded_files"]) == ["f1.pdf", "f2.pdf", "f3.pdf"], result["uploaded_files"]
    print("[PASS] todos presentes -> nada reenviado (sem duplicar)")


def test_only_absent_isolated() -> None:
    # 2 presentes (f1,f2), 1 ausente (f3)
    def split(batch):
        present = [i for i in batch if i["file_name"] in ("f1.pdf", "f2.pdf")]
        absent = [i for i in batch if i["file_name"] == "f3.pdf"]
        return present, absent

    result, handle_calls = _run_loop(split)
    assert len(handle_calls) == 1 and _names(handle_calls[0]) == ["f3.pdf"], handle_calls
    assert _names(result["uploaded_files"]) == ["f1.pdf", "f2.pdf", "f3.pdf"], result["uploaded_files"]
    print("[PASS] parte presente -> isola SO o ausente (f3)")


def test_none_present_isolates_whole_batch() -> None:
    result, handle_calls = _run_loop(lambda batch: ([], list(batch)))
    assert len(handle_calls) == 1 and _names(handle_calls[0]) == ["f1.pdf", "f2.pdf", "f3.pdf"], handle_calls
    print("[PASS] nenhum presente -> isola o lote inteiro (comportamento atual)")


def test_verify_fallback_on_error() -> None:
    """A verificacao real cai para ([], batch) quando o F5/leitura lanca excecao."""
    import app.services.playwright.playground_monitor as pm
    orig = pm.f5_reopen_files
    pm.f5_reopen_files = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("F5 falhou"))
    try:
        batch = _batch(2)
        present, absent = pu.verify_batch_present_in_workspace(_FakePage(), {}, "WS", batch, _log)
        assert present == [] and _names(absent) == ["f1.pdf", "f2.pdf"], (present, absent)
        print("[PASS] verificacao falha -> fallback ([], batch) preservado")
    finally:
        pm.f5_reopen_files = orig


if __name__ == "__main__":
    test_all_present_no_resend()
    test_only_absent_isolated()
    test_none_present_isolates_whole_batch()
    test_verify_fallback_on_error()
    print("\nTODOS OS TESTES ANTI-DUPLICACAO DE UPLOAD PASSARAM.")
