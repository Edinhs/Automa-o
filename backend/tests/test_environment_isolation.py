"""Isolamento dual-environment: a resolucao por ContextVar e o cache de engines.

Cobre o nucleo do design (CLAUDE.md): cada request carrega o ambiente num ContextVar,
e DB URL/engine sao resolvidos por ambiente e cacheados por URL.
"""

from app.core.config import (
    current_environment,
    database_url_for_environment,
    environment_scope,
    normalize_environment,
    set_current_environment,
    reset_current_environment,
)
from app.db.session import engine_for_environment


def test_normalize_environment_aliases():
    assert normalize_environment("dev") == "developer"
    assert normalize_environment("development") == "developer"
    assert normalize_environment("desenvolvedor") == "developer"
    assert normalize_environment("operational") == "operational"
    assert normalize_environment(None) == "operational"
    assert normalize_environment("qualquer-coisa") == "operational"


def test_context_var_controla_url_resolvida():
    token = set_current_environment("developer")
    try:
        assert current_environment() == "developer"
        assert database_url_for_environment() == database_url_for_environment("developer")
    finally:
        reset_current_environment(token)
    # Fora do escopo, volta ao default operational.
    assert current_environment() == "operational"


def test_environment_scope_restaura_apos_sair():
    assert current_environment() == "operational"
    with environment_scope("developer") as env:
        assert env == "developer"
        assert current_environment() == "developer"
    assert current_environment() == "operational"


def test_operational_e_developer_tem_urls_distintas_por_padrao():
    assert database_url_for_environment("operational") != database_url_for_environment("developer")


def test_engine_cacheado_por_ambiente():
    op1 = engine_for_environment("operational")
    op2 = engine_for_environment("operational")
    dev = engine_for_environment("developer")
    assert op1 is op2  # mesmo ambiente -> mesmo engine (cache por URL)
    assert op1 is not dev  # ambientes distintos -> engines distintos
