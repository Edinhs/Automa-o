"""compute_next_run: calculo do proximo disparo dos agendamentos.

Schedule e instanciavel em memoria (sem sessao). Cobre once/daily/weekly/monthly/interval
e o respeito a status inativo e end_date.
"""

from datetime import datetime

from app.models.schedule import Schedule
from app.services.schedule_runner import compute_next_run


def _schedule(**kwargs) -> Schedule:
    base = {"status": "active"}
    base.update(kwargs)
    return Schedule(**base)


def test_daily_hoje_quando_horario_ainda_nao_passou():
    s = _schedule(frequency_type="daily", time_of_day="08:00")
    now = datetime(2026, 6, 3, 7, 0)
    assert compute_next_run(s, now) == datetime(2026, 6, 3, 8, 0)


def test_daily_amanha_quando_horario_ja_passou():
    s = _schedule(frequency_type="daily", time_of_day="08:00")
    now = datetime(2026, 6, 3, 9, 0)
    assert compute_next_run(s, now) == datetime(2026, 6, 4, 8, 0)


def test_status_inativo_nao_agenda():
    s = _schedule(frequency_type="daily", time_of_day="08:00", status="paused")
    assert compute_next_run(s, datetime(2026, 6, 3, 7, 0)) is None


def test_once_sem_execucao_anterior():
    run = datetime(2026, 6, 10, 14, 30)
    s = _schedule(frequency_type="once", run_date=run)
    assert compute_next_run(s, datetime(2026, 6, 3, 7, 0)) == run


def test_once_ja_executado_nao_reagenda():
    s = _schedule(
        frequency_type="once",
        run_date=datetime(2026, 6, 10, 14, 30),
        last_run_at=datetime(2026, 6, 10, 14, 30),
    )
    assert compute_next_run(s, datetime(2026, 6, 11, 7, 0)) is None


def test_interval_avanca_para_o_proximo_passo_futuro():
    s = _schedule(
        frequency_type="interval",
        interval_minutes=30,
        start_date=datetime(2026, 6, 3, 8, 0),
    )
    now = datetime(2026, 6, 3, 8, 45)
    assert compute_next_run(s, now) == datetime(2026, 6, 3, 9, 0)


def test_end_date_no_passado_bloqueia_daily():
    s = _schedule(
        frequency_type="daily",
        time_of_day="08:00",
        end_date=datetime(2026, 6, 1, 0, 0),
    )
    assert compute_next_run(s, datetime(2026, 6, 3, 7, 0)) is None


def test_monthly_respeita_dia_do_mes():
    s = _schedule(frequency_type="monthly", time_of_day="08:00", day_of_month=15)
    now = datetime(2026, 6, 3, 7, 0)
    assert compute_next_run(s, now) == datetime(2026, 6, 15, 8, 0)
