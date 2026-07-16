"""0013 report language (PT/EN)

Adiciona o idioma opcional do relatorio em duas colunas, ambas com server_default "pt" (nenhuma
mudanca de comportamento para dados existentes -> continuam em portugues):

  - execution_reports.language   -> idioma em que o conteudo do relatorio foi gerado; usado no
    re-download/fallback para regenerar no MESMO idioma.
  - schedules.report_language    -> idioma dos relatorios gerados por aquele agendamento;
    propagado por run_due_report_schedule -> persist_report(..., language=...).

Idempotente (checa o schema antes de agir, no estilo das migracoes 0009-0012). ADD COLUMN com
server_default e suportado nativamente por SQLite e PostgreSQL (sem batch/move-and-copy); o DROP
no downgrade usa batch_alter_table por causa do SQLite.

Revision ID: a9c2e4f6b731
Revises: f1a2b3c4d5e6
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa


revision = "a9c2e4f6b731"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    if "language" not in _columns("execution_reports"):
        op.add_column(
            "execution_reports",
            sa.Column("language", sa.String(), nullable=False, server_default="pt"),
        )
    if "report_language" not in _columns("schedules"):
        op.add_column(
            "schedules",
            sa.Column("report_language", sa.String(), nullable=False, server_default="pt"),
        )


def downgrade() -> None:
    if "report_language" in _columns("schedules"):
        with op.batch_alter_table("schedules") as batch_op:
            batch_op.drop_column("report_language")
    if "language" in _columns("execution_reports"):
        with op.batch_alter_table("execution_reports") as batch_op:
            batch_op.drop_column("language")
