"""Automacao 'PNG -> Teams': monitora uma pasta (TEAMS_PNG_WATCH_FOLDER) para um arquivo PNG
novo (por conteudo/sha256, nao apenas por nome) e envia SOMENTE o arquivo novo para um chat do
Teams via Playwright (app.services.playwright.teams_delivery.deliver_file_teams_playwright).

Dois modos, escolhidos por TEAMS_PNG_DELIVERY_MODE (.env):
  - "schedule"   -> so verifica a pasta no dia/hora fixos
                    (TEAMS_PNG_DELIVERY_DAY_OF_WEEK / TEAMS_PNG_DELIVERY_TIME).
  - "continuous" -> verifica a pasta a cada TEAMS_PNG_DELIVERY_POLL_INTERVAL_SECONDS,
                     independente do dia -- assim que aparece um PNG novo, envia.

100% dirigido por .env: nao exige criar Automation/Schedule pelo dashboard. Pensado para o
caso de uso "um processo externo derruba um PNG novo numa pasta (ex.: toda segunda); o HUB
manda so o arquivo novo pro Teams, nunca reenvia os antigos".

Estado (ultimo arquivo enviado + ultima checagem) fica em um JSON local
(data/teams_png_delivery_state.json), lido/escrito tanto pelo processo do backend (FastAPI,
que decide QUANDO verificar e enfileira a task) quanto pelo processo do agente local (que
confirma o envio e marca o arquivo como enviado) -- por isso e' baseado em arquivo, e nao em
memoria (os dois rodam em processos python separados).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.config import BACKEND_DIR, settings
from app.core.timezone import now_sao_paulo_naive

# Mesmo mapeamento de aliases de dia da semana usado no schedule_runner (pt/en, abreviado ou
# nao). Duplicado aqui (em vez de importar de schedule_runner) para nao criar dependencia do
# backend (FastAPI) no processo do agente local, que tambem importa este modulo.
WEEKDAY_ALIASES = {
    "seg": 0, "segunda": 0, "mon": 0, "monday": 0,
    "ter": 1, "terça": 1, "terca": 1, "tue": 1, "tuesday": 1,
    "qua": 2, "quarta": 2, "wed": 2, "wednesday": 2,
    "qui": 3, "quinta": 3, "thu": 3, "thursday": 3,
    "sex": 4, "sexta": 4, "fri": 4, "friday": 4,
    "sab": 5, "sábado": 5, "sabado": 5, "sat": 5, "saturday": 5,
    "dom": 6, "domingo": 6, "sun": 6, "sunday": 6,
}

_STATE_PATH = BACKEND_DIR / "data" / "teams_png_delivery_state.json"


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_latest_png(folder: Path) -> Optional[Path]:
    """Retorna o .png mais recente (por mtime) na pasta, ou None se nao existir/estiver vazia."""
    if not folder.is_dir():
        return None
    candidates = sorted(
        (p for p in folder.glob("*.png") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _parse_time_of_day(value: str) -> tuple[int, int]:
    value = (value or "").strip() or "09:00"
    hour_str, _, minute_str = value.partition(":")
    try:
        hour = int(hour_str)
        minute = int(minute_str) if minute_str else 0
    except ValueError:
        hour, minute = 9, 0
    return max(0, min(hour, 23)), max(0, min(minute, 59))


def _is_schedule_due(now: datetime, state: dict[str, Any]) -> bool:
    """True quando 'now' esta dentro da janela do dia/hora configurados e essa janela semanal
    ainda nao foi verificada (evita disparar varias vezes no mesmo dia)."""
    weekday_name = str(settings.TEAMS_PNG_DELIVERY_DAY_OF_WEEK or "monday").strip().lower()
    target_weekday = WEEKDAY_ALIASES.get(weekday_name, 0)
    hour, minute = _parse_time_of_day(settings.TEAMS_PNG_DELIVERY_TIME)

    if now.weekday() != target_weekday:
        return False
    scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_today:
        return False

    last_check_raw = state.get("last_schedule_check_at")
    if last_check_raw:
        try:
            last_check = datetime.fromisoformat(last_check_raw)
            if last_check >= scheduled_today:
                return False  # ja verificou nesta janela semanal
        except ValueError:
            pass
    return True


def _is_continuous_due(now: datetime, state: dict[str, Any]) -> bool:
    interval = max(int(settings.TEAMS_PNG_DELIVERY_POLL_INTERVAL_SECONDS or 300), 30)
    last_check_raw = state.get("last_continuous_check_at")
    if not last_check_raw:
        return True
    try:
        last_check = datetime.fromisoformat(last_check_raw)
    except ValueError:
        return True
    return (now - last_check) >= timedelta(seconds=interval)


def check_for_new_png(log: Optional[Callable] = None) -> Optional[dict[str, Any]]:
    """Chamado periodicamente pelo runner de agendamentos (processo do backend). Se a
    automacao estiver habilitada e for a hora certa (modo schedule) ou o intervalo tiver
    passado (modo continuous), verifica se ha um PNG novo (por sha256, nao so por nome) na
    pasta monitorada.

    Retorna None se a automacao estiver desligada/mal configurada, ou um dict com 'queued'
    (True se ha um PNG novo pronto para envio) e detalhes do arquivo.
    """
    def _log(level: str, message: str, **kwargs) -> None:
        if log:
            log(level, message, **kwargs)

    if not settings.TEAMS_PNG_DELIVERY_ENABLED:
        return None
    folder_raw = str(settings.TEAMS_PNG_WATCH_FOLDER or "").strip()
    if not folder_raw:
        _log("warning", "TEAMS_PNG_DELIVERY_ENABLED=true mas TEAMS_PNG_WATCH_FOLDER nao configurado no .env.")
        return None

    now = now_sao_paulo_naive()
    state = _load_state()
    mode = str(settings.TEAMS_PNG_DELIVERY_MODE or "schedule").strip().lower()
    due = _is_continuous_due(now, state) if mode == "continuous" else _is_schedule_due(now, state)
    if not due:
        return {"queued": False, "reason": "not_due", "mode": mode}

    # Marca a checagem (mesmo se nao houver arquivo novo) para nao disparar de novo na mesma
    # janela (schedule) ou antes do proximo intervalo (continuous).
    state_key = "last_continuous_check_at" if mode == "continuous" else "last_schedule_check_at"
    state[state_key] = now.isoformat()
    _save_state(state)

    folder = Path(folder_raw)
    latest = find_latest_png(folder)
    if not latest:
        _log("info", f"[teams_png_watch] Nenhum PNG encontrado em {folder_raw} (modo={mode}).")
        return {"queued": False, "reason": "no_png_found", "mode": mode}

    sha256 = file_sha256(latest)
    if state.get("last_sent_sha256") == sha256:
        _log("info", f"[teams_png_watch] PNG mais recente ({latest.name}) ja foi enviado antes (mesmo conteudo).")
        return {"queued": False, "reason": "already_sent", "file": latest.name, "mode": mode}

    return {
        "queued": True,
        "file_path": str(latest),
        "file_name": latest.name,
        "sha256": sha256,
        "mode": mode,
    }


def mark_png_sent(sha256: str, file_name: str) -> None:
    """Chamado pelo agente local APOS o envio ao Teams ser confirmado com sucesso -- so entao
    o arquivo passa a contar como 'ja enviado'. Se o envio falhar, o estado nao e' atualizado
    e a proxima checagem tenta de novo o mesmo arquivo (nao fica marcado como enviado sem ter
    ido de fato)."""
    state = _load_state()
    state["last_sent_sha256"] = sha256
    state["last_sent_file"] = file_name
    state["last_sent_at"] = now_sao_paulo_naive().isoformat()
    _save_state(state)


def resolve_chat_name() -> str:
    return str(settings.TEAMS_PNG_DELIVERY_CHAT_NAME or settings.TEAMS_DELIVERY_CHAT_NAME or "1:1 Ederson").strip()


def resolve_text_message(file_name: str) -> str:
    text = str(settings.TEAMS_PNG_DELIVERY_TEXT or "").strip()
    return text or f"Novo relatorio disponivel: {file_name}"
