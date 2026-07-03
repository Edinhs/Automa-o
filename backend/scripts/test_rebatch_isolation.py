r"""
test_rebatch_isolation.py -- Teste DETERMINISTICO (mock, sem navegador) do reenvio em
lote apos isolamento do arquivo corrompido (Tarefa 3).

Faz mock de upload_batch / recover_upload_area_in_same_session / finalize_corrupted e
exercita isolate_one_by_one para provar:
  1) Achado o corrompido, o RESTANTE sai em UMA chamada de lote (nao 1-a-1).
  2) Um SEGUNDO arquivo corrompido oculto ainda e detectado e movido.
  3) Culpado por ultimo: sem rebatch, sem regressao.
  4) Todos saudaveis: comporta como antes.

Uso (raiz do repo):
    & ".\backend\.venv\Scripts\python.exe" ".\backend\scripts\test_rebatch_isolation.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services.playwright import playground_upload as pu  # noqa: E402
from app.services.playwright.errors import UploadFailed  # noqa: E402


def _item(name: str) -> dict:
    return {"file_name": name, "temp_path": f"/tmp/{name}", "file_id": name}


def _log(level: str, message: str, **_kw) -> None:
    pass  # silencioso; foco nas assercoes


def run_scenario(name: str, files: list[str], bad: set[str], batch_size: int = 5):
    calls: list[list[str]] = []
    corrupted: list[str] = []

    def mock_upload_batch(page, batch, log, **kwargs):
        names = [it["file_name"] for it in batch]
        calls.append(names)
        bad_in = [n for n in names if n in bad]
        if bad_in:
            raise UploadFailed("uploading error")
        return [{"file_name": it["file_name"], "status": "uploaded"} for it in batch]

    def mock_recover(*_a, **_k):
        return None

    def mock_finalize(items, log, on_file_error):
        for it in items:
            corrupted.append(it["file_name"])

    # Monkeypatch dos globais do modulo
    orig = (pu.upload_batch, pu.recover_upload_area_in_same_session, pu.finalize_corrupted)
    pu.upload_batch = mock_upload_batch
    pu.recover_upload_area_in_same_session = mock_recover
    pu.finalize_corrupted = mock_finalize
    try:
        payload = {"batch_size": batch_size}
        result = pu.isolate_one_by_one(
            page=None,
            batch=[_item(f) for f in files],
            payload=payload,
            workspace_name="ws-test",
            log=_log,
            on_file_error=None,
            should_continue=None,
            task_id=1,
        )
    finally:
        pu.upload_batch, pu.recover_upload_area_in_same_session, pu.finalize_corrupted = orig

    healthy = sorted({it["file_name"] for it in result})
    batched_calls = [c for c in calls if len(c) > 1]
    print(f"\n[{name}]")
    print(f"  files={files} bad={sorted(bad)}")
    print(f"  upload_batch calls = {calls}")
    print(f"  corrompidos movidos = {sorted(corrupted)}")
    print(f"  saudaveis enviados  = {healthy}")
    print(f"  chamadas em LOTE (>1) = {batched_calls}")
    return calls, sorted(corrupted), healthy, batched_calls


def main() -> None:
    ok = True

    # 1) Um corrompido no meio: restante [C,D,E] deve sair em UMA chamada de lote.
    calls, corrupted, healthy, batched = run_scenario("1 corrompido no meio", ["A", "B", "C", "D", "E"], {"B"})
    assert corrupted == ["B"], f"esperava corrompido B, veio {corrupted}"
    assert healthy == ["A", "C", "D", "E"], f"saudaveis errados: {healthy}"
    assert ["C", "D", "E"] in calls, "restante NAO saiu em lote unico [C,D,E]"
    assert len(calls) == 3, f"esperava 3 chamadas (A, B, [C,D,E]); veio {len(calls)}"
    print("  => PASS: restante reagrupado em 1 lote (3 chamadas, nao 5).")

    # 2) Dois corrompidos: ambos detectados, saudaveis enviados.
    calls, corrupted, healthy, batched = run_scenario("2 corrompidos", ["A", "B", "C", "D", "E"], {"B", "D"})
    assert corrupted == ["B", "D"], f"esperava B e D corrompidos, veio {corrupted}"
    assert healthy == ["A", "C", "E"], f"saudaveis errados: {healthy}"
    assert any(len(c) > 1 for c in calls), "esperava ao menos uma tentativa em lote"
    print("  => PASS: segundo corrompido detectado; saudaveis A,C,E enviados.")

    # 3) Culpado por ultimo: sem rebatch (remaining vazio), sem regressao.
    calls, corrupted, healthy, batched = run_scenario("culpado por ultimo", ["A", "B", "C", "D"], {"D"})
    assert corrupted == ["D"], f"esperava D, veio {corrupted}"
    assert healthy == ["A", "B", "C"], f"saudaveis errados: {healthy}"
    assert batched == [], f"nao deveria haver chamada em lote; veio {batched}"
    print("  => PASS: culpado por ultimo, sem rebatch, sem regressao.")

    # 4) Todos saudaveis: comporta como antes (1-a-1, sem corrompidos).
    calls, corrupted, healthy, batched = run_scenario("todos saudaveis", ["A", "B", "C"], set())
    assert corrupted == [], f"nao deveria haver corrompido; veio {corrupted}"
    assert healthy == ["A", "B", "C"], f"saudaveis errados: {healthy}"
    assert len(calls) == 3, f"esperava 3 envios individuais; veio {len(calls)}"
    print("  => PASS: todos saudaveis, comportamento preservado.")

    # 5) batch_size=2 com restante grande: restante [C,D,E,F] -> sub-lotes [C,D],[E,F].
    calls, corrupted, healthy, batched = run_scenario("rebatch chunked", ["A", "B", "C", "D", "E", "F"], {"B"}, batch_size=2)
    assert corrupted == ["B"], f"{corrupted}"
    assert healthy == ["A", "C", "D", "E", "F"], f"{healthy}"
    assert ["C", "D"] in calls and ["E", "F"] in calls, "restante nao foi chunked em sub-lotes [C,D],[E,F]"
    print("  => PASS: restante reagrupado em sub-lotes conforme batch_size.")

    print("\nTODOS OS CENARIOS PASSARAM." if ok else "\nFALHAS DETECTADAS.")


if __name__ == "__main__":
    main()
