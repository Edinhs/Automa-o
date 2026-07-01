"""
Teste in-process do agendamento de relatorios (ambiente developer, sem navegador).

Prova duas garantias pedidas:

  1. Um relatorio AGENDADO e entregue no caminho configurado no .env
     (REPORT_DELIVERY_PATH / DEVELOPER_REPORT_DELIVERY_PATH). O teste cria uma
     pasta de teste e aponta o env var para ela ANTES de importar a config.
  2. Ao haver 2 agendamentos de relatorio devidos no mesmo tick, o de formato
     JSON sempre salva PRIMEIRO (sort estavel em run_due_schedules_once).

Tambem valida que o nome do relatorio carrega data/hora e que o .json gerado e
um JSON valido. Roda totalmente isolado: pausa temporariamente quaisquer outros
agendamentos ativos, usa o banco developer e limpa tudo o que cria.

Uso (a partir da raiz do repo):
  backend\\.venv\\Scripts\\python.exe backend\\scripts\\test_scheduled_report_json_delivery.py
"""
import json
import os
import shutil
import sys
from datetime import timedelta
from pathlib import Path

# backend/ = pai da pasta scripts/. Precisa estar no sys.path para "import app".
# Tambem usamos cwd=backend/ porque os URLs SQLite do projeto sao relativos
# (sqlite:///./data/...), exatamente como o backend roda em producao.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

# Caminho de entrega de TESTE: setar o env var ANTES de importar a config, pois
# pydantic BaseSettings le o ambiente no momento da instanciacao do singleton.
DELIVERY_DIR = BACKEND_DIR / "data" / "developer" / "report_delivery_test"
if DELIVERY_DIR.exists():
    shutil.rmtree(DELIVERY_DIR, ignore_errors=True)
DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
os.environ["DEVELOPER_REPORT_DELIVERY_PATH"] = str(DELIVERY_DIR)

from app.core.config import environment_scope, report_delivery_dir, runtime_path  # noqa: E402
from app.core.timezone import now_sao_paulo_naive  # noqa: E402
from app.db.session import session_for_environment  # noqa: E402
from app.models.execution import ExecutionReport  # noqa: E402
from app.models.schedule import Schedule  # noqa: E402
from app.services.schedule_runner import ACTIVE_STATUS_VALUES, PAUSED_STATUS, run_due_schedules_once  # noqa: E402

REPORT_TYPE = "Relatório Geral"


def log(msg):
    print(msg, flush=True)


def main() -> int:
    # Confere que o env var foi mesmo absorvido pela config.
    resolved = report_delivery_dir("developer")
    assert resolved is not None and resolved == DELIVERY_DIR, (
        f"REPORT_DELIVERY_PATH nao resolveu para a pasta de teste: {resolved} != {DELIVERY_DIR}"
    )
    log(f"Pasta de entrega (.env) resolvida: {resolved}")

    created_schedule_ids: list[int] = []
    created_report_ids: list[int] = []
    paused_for_test: list[int] = []

    with environment_scope("developer"):
        db = session_for_environment("developer")
        try:
            now = now_sao_paulo_naive()
            past = now - timedelta(minutes=1)

            # Isolamento: pausa qualquer agendamento ativo pre-existente para que
            # nenhum outro dispare neste tick (e nao abra navegador).
            existing = (
                db.query(Schedule)
                .filter(
                    Schedule.is_deleted == False,  # noqa: E712
                    Schedule.status.in_(ACTIVE_STATUS_VALUES),
                )
                .all()
            )
            for sch in existing:
                sch.status = PAUSED_STATUS
                paused_for_test.append(sch.id)
            if paused_for_test:
                db.commit()
                log(f"Pausados temporariamente {len(paused_for_test)} agendamentos ativos pre-existentes.")

            # Cria o XLSX PRIMEIRO (id menor) para provar que o sort forca o JSON
            # na frente mesmo tendo sido inserido depois.
            xlsx_sched = Schedule(
                name="[TESTE] Agendado XLSX",
                frequency_type="once",
                report_type=REPORT_TYPE,
                report_format="xlsx",
                status="active",
                next_run_at=past,
                run_date=past,
                start_date=past,
            )
            db.add(xlsx_sched)
            db.commit()
            db.refresh(xlsx_sched)
            created_schedule_ids.append(xlsx_sched.id)

            json_sched = Schedule(
                name="[TESTE] Agendado JSON",
                frequency_type="once",
                report_type=REPORT_TYPE,
                report_format="json",
                status="active",
                next_run_at=past,
                run_date=past,
                start_date=past,
            )
            db.add(json_sched)
            db.commit()
            db.refresh(json_sched)
            created_schedule_ids.append(json_sched.id)
            log(f"Agendamentos criados: xlsx#{xlsx_sched.id} (antes), json#{json_sched.id} (depois).")

            max_report_id_before = db.query(ExecutionReport.id).order_by(ExecutionReport.id.desc()).first()
            max_report_id_before = max_report_id_before[0] if max_report_id_before else 0

            # Executa o scheduler (contem o sort JSON-first).
            triggered = run_due_schedules_once(now=now, db=db)
            log(f"run_due_schedules_once disparou {triggered} agendamento(s).")

            new_reports = (
                db.query(ExecutionReport)
                .filter(ExecutionReport.id > max_report_id_before)
                .order_by(ExecutionReport.id.asc())
                .all()
            )
            created_report_ids = [r.id for r in new_reports]
            by_fmt = {}
            for r in new_reports:
                fmt = (r.type or "").split("|")[-1].lower()
                by_fmt[fmt] = r
            log("Relatorios gerados:")
            for r in new_reports:
                log(f"  id={r.id} name={r.name!r} type={r.type} file={r.file_path}")

            # --- Asserções ---
            assert "json" in by_fmt, "Relatorio JSON agendado nao foi gerado."
            assert "xlsx" in by_fmt, "Relatorio XLSX agendado nao foi gerado."
            json_rep, xlsx_rep = by_fmt["json"], by_fmt["xlsx"]

            # (a) JSON salva PRIMEIRO: id menor e created_at <= (commit anterior).
            assert json_rep.id < xlsx_rep.id, (
                f"JSON deveria salvar primeiro (id menor): json#{json_rep.id} vs xlsx#{xlsx_rep.id}."
            )
            assert json_rep.created_at <= xlsx_rep.created_at, "created_at do JSON deveria ser <= do XLSX."
            log("OK: o relatorio JSON foi salvo antes do XLSX.")

            # (b) Arquivos fisicos existem na subpasta agendados/ do ambiente.
            agendados_dir = runtime_path("REPORTS_PATH") / "agendados"
            for r in (json_rep, xlsx_rep):
                p = Path(r.file_path)
                assert p.exists(), f"Arquivo fisico do relatorio nao existe: {p}"
                assert p.parent == agendados_dir, f"Relatorio agendado fora de agendados/: {p}"
            log(f"OK: arquivos gerados em {agendados_dir}")

            # (c) Entregues na pasta do .env (+ sidecar). O sidecar usa SEMPRE .meta.json
            #     (gatilho inequivoco do Power Automate; nao colide com o relatorio .json).
            json_name = Path(json_rep.file_path).name
            xlsx_name = Path(xlsx_rep.file_path).name
            json_delivered = DELIVERY_DIR / json_name
            xlsx_delivered = DELIVERY_DIR / xlsx_name
            json_sidecar = DELIVERY_DIR / f"{Path(json_name).stem}.meta.json"
            xlsx_sidecar = DELIVERY_DIR / f"{Path(xlsx_name).stem}.meta.json"
            assert json_delivered.exists(), f"Relatorio JSON nao entregue no caminho do .env: {json_delivered}"
            assert xlsx_delivered.exists(), f"Relatorio XLSX nao entregue no caminho do .env: {xlsx_delivered}"
            assert json_sidecar.exists(), f"Sidecar do JSON ausente: {json_sidecar}"
            assert xlsx_sidecar.exists(), f"Sidecar do XLSX ausente: {xlsx_sidecar}"
            # PDF companheiro (anexo do Teams) presente para ambos os formatos.
            assert (DELIVERY_DIR / f"{Path(json_name).stem}.pdf").exists(), "PDF companheiro do JSON ausente"
            assert (DELIVERY_DIR / f"{Path(xlsx_name).stem}.pdf").exists(), "PDF companheiro do XLSX ausente"
            # O relatorio JSON entregue NAO pode ter sido sobrescrito pelo sidecar.
            delivered_payload = json.loads(json_delivered.read_text(encoding="utf-8"))
            assert "sections" in delivered_payload, "Relatorio JSON entregue nao tem 'sections' (foi sobrescrito?)."
            log(f"OK: ambos entregues em {DELIVERY_DIR} (com sidecar, sem colisao).")

            # (d) Conteudo JSON do relatorio gerado e valido.
            payload = json.loads(Path(json_rep.file_path).read_text(encoding="utf-8"))
            assert payload.get("report_type") == REPORT_TYPE, "report_type do JSON divergente."
            assert isinstance(payload.get("sections"), list) and payload["sections"], "JSON sem sections."
            log("OK: conteudo do relatorio JSON e um JSON valido com sections.")

            # (e) Nome do relatorio carrega data/hora (dd/mm/aaaa hh:mm).
            import re

            for r in (json_rep, xlsx_rep):
                assert re.search(r" - \d{2}/\d{2}/\d{4} \d{2}:\d{2}$", r.name or ""), (
                    f"Nome sem data/hora: {r.name!r}"
                )
            log("OK: nomes dos relatorios contem data e hora.")

            log("\n" + "=" * 60)
            log(" TESTE OK: JSON entregue no caminho do .env e salvo PRIMEIRO. ")
            log("=" * 60)
            return 0
        finally:
            # Limpeza: remove relatorios/agendamentos de teste e restaura status.
            try:
                for rid in created_report_ids:
                    rep = db.get(ExecutionReport, rid)
                    if rep:
                        if rep.file_path and Path(rep.file_path).exists():
                            Path(rep.file_path).unlink()
                        db.delete(rep)
                for sid in created_schedule_ids:
                    sch = db.get(Schedule, sid)
                    if sch:
                        db.delete(sch)
                for sid in paused_for_test:
                    sch = db.get(Schedule, sid)
                    if sch:
                        sch.status = "active"
                db.commit()
            except Exception as exc:  # noqa: BLE001
                log(f"Aviso: limpeza parcial ({exc}).")
            finally:
                db.close()
            shutil.rmtree(DELIVERY_DIR, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
