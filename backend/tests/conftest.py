"""Fixtures compartilhadas dos testes do backend.

Mantém os testes offline e sem tocar nos bancos reais: cada teste que precisa de
banco recebe uma sessao SQLite em memoria com o schema completo (todos os models
sao importados via app.models para registrar as tabelas no Base.metadata).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — registra todos os models no Base.metadata
from app.db.session import Base


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
