"""0011 schedule deliver_to_folder

Adiciona schedules.deliver_to_folder: quando True, o relatorio gerado por aquele agendamento
tambem e copiado para a pasta de entrega (REPORT_DELIVERY_PATH / Power Automate). Default False
-> o relatorio fica apenas em REPORTS_PATH (backend/data/reports). Torna a entrega ao .env um
opt-in por agendamento (botao no modal "Agendar Relatorio"), em vez de copiar TODO relatorio.

Idempotente: so adiciona a coluna se ainda nao existir. Sem PRAGMA -> SQLite e PostgreSQL.

Revision ID: e7b3d5a9c528
Revises: d5a2c8f1b426
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "e7b3d5a9c528"
down_revision = "d5a2c8f1b426"
branch_labels = None
depends_on = None


def _schedules_columns() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns("schedules")}


def upgrade() -> None:
    if "deliver_to_folder" not in _schedules_columns():
        # server_default=false garante valor coerente nas linhas existentes (SQLite e PostgreSQL).
        op.add_column(
            "schedules",
            sa.Column("deliver_to_folder", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if "deliver_to_folder" in _schedules_columns():
        with op.batch_alter_table("schedules") as batch_op:
            batch_op.drop_column("deliver_to_folder")
