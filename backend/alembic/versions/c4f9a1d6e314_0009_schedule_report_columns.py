"""0009 schedule report columns

Adiciona schedules.report_type e schedules.report_format a cadeia oficial do Alembic.

Essas colunas existiam APENAS via o patch de startup app.db.migrate_schedules (que usa
PRAGMA table_info, exclusivo de SQLite). Sem esta migracao, um `alembic upgrade head` em um
banco NOVO (inclusive PostgreSQL) nao criava as colunas e o app quebrava ao consultar o
Schedule. Agora o schema e 100% reproduzivel pelo Alembic e portavel.

Idempotente: so adiciona a coluna que ainda nao existe, para ser segura em bancos que ja a
receberam pelo patch legado (dev/operacional atuais). Sem PRAGMA -> funciona em SQLite e
PostgreSQL.

Revision ID: c4f9a1d6e314
Revises: b8e5f7a9c013
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa


revision = "c4f9a1d6e314"
down_revision = "b8e5f7a9c013"
branch_labels = None
depends_on = None


def _schedules_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns("schedules")}


def upgrade() -> None:
    existing = _schedules_columns()
    # ALTER TABLE ADD COLUMN (nullable) e suportado nativamente por SQLite e PostgreSQL,
    # nao exige batch/move-and-copy.
    if "report_type" not in existing:
        op.add_column("schedules", sa.Column("report_type", sa.String(), nullable=True))
    if "report_format" not in existing:
        op.add_column("schedules", sa.Column("report_format", sa.String(), nullable=True))


def downgrade() -> None:
    existing = _schedules_columns()
    # batch_alter_table para compatibilidade de DROP COLUMN no SQLite.
    with op.batch_alter_table("schedules") as batch_op:
        if "report_format" in existing:
            batch_op.drop_column("report_format")
        if "report_type" in existing:
            batch_op.drop_column("report_type")
