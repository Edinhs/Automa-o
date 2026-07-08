from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import database_url_for_environment, resolve_backend_path
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
            # 15s: o agente registra arquivos em rajada (2 commits por arquivo) enquanto
            # scheduler/monitor tambem gravam; com 5s um lote grande estourava
            # "database is locked" -> 500 no POST /api/files.
            cursor.execute("PRAGMA busy_timeout=15000")
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
    except Exception:
        # Sem este rollback, uma requisicao que estoura no meio de uma transacao
        # devolvia a conexao ao pool ainda "suja" -> a proxima requisicao que
        # pegasse essa conexao falhava com PendingRollbackError (500 em cascata,
        # intermitente e espalhado por varios endpoints).
        db.rollback()
        raise
    finally:
        db.close()
