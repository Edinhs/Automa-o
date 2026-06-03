"""Modelo de auth (deps.py): caminhos AUTH_DISABLED, JWT ausente e X-Agent-Token.

Confirma o comportamento POR DESIGN do release offline (AUTH_DISABLED=true) e que o
token do agente e validado por compare_digest antes de qualquer fallback.
"""

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.user import User
from app.routers.deps import (
    get_current_user,
    require_agent_or_user,
)


def test_auth_disabled_cria_admin_local(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", True)
    user = get_current_user(db=db_session, token=None)
    assert isinstance(user, User)
    assert user.role == "admin"
    assert user.status == "active"


def test_auth_habilitado_sem_token_rejeita(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", False)
    with pytest.raises(HTTPException) as exc:
        get_current_user(db=db_session, token=None)
    assert exc.value.status_code == 401


def test_agent_token_correto_autentica_como_agente(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", False)
    monkeypatch.setattr(settings, "AGENT_SHARED_TOKEN", "segredo-do-agente")
    result = require_agent_or_user(
        db=db_session, token=None, x_agent_token="segredo-do-agente"
    )
    assert result == {"kind": "agent"}


def test_agent_token_errado_sem_bearer_rejeita(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", False)
    monkeypatch.setattr(settings, "AGENT_SHARED_TOKEN", "segredo-do-agente")
    with pytest.raises(HTTPException) as exc:
        require_agent_or_user(db=db_session, token=None, x_agent_token="errado")
    assert exc.value.status_code == 401


def test_agent_token_errado_com_auth_disabled_cai_no_admin_local(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_DISABLED", True)
    monkeypatch.setattr(settings, "AGENT_SHARED_TOKEN", "segredo-do-agente")
    result = require_agent_or_user(db=db_session, token=None, x_agent_token="errado")
    assert isinstance(result, User)
    assert result.role == "admin"
