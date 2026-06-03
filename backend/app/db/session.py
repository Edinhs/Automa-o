from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import database_url_for_environment, resolve_backend_path, settings
import os


Base = declarative_base()
_engines = {}
_session_factories = {}


def _create_engine(database_url: str):
    if database_url.startswith("sqlite:///"):
        database_path = database_url.replace("sqlite:///", "", 1)
        if database_path != ":memory:":
            os.makedirs(resolve_backend_path(database_path).parent, exist_ok=True)

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    created_engine = create_engine(
        database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    if database_url.startswith("sqlite"):
        @event.listens_for(created_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={int(settings.SQLITE_BUSY_TIMEOUT_MS)}")
            cursor.close()
    return created_engine


def engine_for_environment(environment: str | None = None):
    database_url = database_url_for_environment(environment)
    if database_url not in _engines:
        _engines[database_url] = _create_engine(database_url)
    return _engines[database_url]


def session_factory_for_environment(environment: str | None = None):
    database_url = database_url_for_environment(environment)
    if database_url not in _session_factories:
        _session_factories[database_url] = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine_for_environment(environment),
        )
    return _session_factories[database_url]


def session_for_environment(environment: str | None = None):
    return session_factory_for_environment(environment)()


engine = engine_for_environment("operational")
SessionLocal = session_factory_for_environment("operational")


def get_db():
    db = session_for_environment()
    try:
        yield db
    finally:
        db.close()
