from sqlalchemy import inspect, text

from app.core.config import SUPPORTED_ENVIRONMENTS
from app.db.session import engine_for_environment, session_for_environment

# Rede de seguranca idempotente para schedules.report_type / report_format.
#
# A fonte de verdade do schema e o Alembic (migracao 0009 cria estas colunas). Este patch de
# startup permanece como auto-correcao para instalacoes que, por algum motivo, nao rodaram a
# migracao — mas agora e PORTAVEL (usa o inspector do SQLAlchemy em vez de PRAGMA), entao nao
# quebra em PostgreSQL nem em outro banco. So adiciona a coluna que falta; nunca duplica.
_SCHEDULE_REPORT_COLUMNS = ("report_type", "report_format")


def run_migrations():
    print("[migration] Verificando colunas de relatorio em schedules (rede de seguranca)...")
    for env in SUPPORTED_ENVIRONMENTS:
        db = session_for_environment(env)
        try:
            inspector = inspect(engine_for_environment(env))
            if "schedules" not in inspector.get_table_names():
                continue  # tabela ainda nao existe (Alembic cuidara disso)
            existing = {col["name"] for col in inspector.get_columns("schedules")}
            for column in _SCHEDULE_REPORT_COLUMNS:
                if column not in existing:
                    # ADD COLUMN nullable: suportado por SQLite e PostgreSQL.
                    db.execute(text(f"ALTER TABLE schedules ADD COLUMN {column} VARCHAR"))
                    print(f"[migration] Coluna '{column}' adicionada a schedules no ambiente {env}.")
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"[migration] Falha ao verificar schedules no ambiente {env}: {exc}")
        finally:
            db.close()
