"""0010 performance indexes

Adiciona indices em FKs e colunas "quentes" (status, content_sha256, next_run_at, created_at,
task_id...) para escala. Os nomes seguem a convencao do SQLAlchemy (ix_<tabela>_<coluna>), que e
o mesmo que `index=True` nos modelos gera — assim Alembic e modelos ficam sem drift.

Idempotente: so cria o indice que ainda nao existe (seguro em bancos que ja tenham parte deles).
Portavel: usa o inspector do SQLAlchemy + op.create_index (SQLite e PostgreSQL).

Revision ID: d5a2c8f1b426
Revises: c4f9a1d6e314
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa


revision = "d5a2c8f1b426"
down_revision = "c4f9a1d6e314"
branch_labels = None
depends_on = None


# (nome_do_indice, tabela, coluna) — nomes identicos aos que index=True gera nos modelos.
INDEXES = [
    ("ix_workspaces_owner_user_id", "workspaces", "owner_user_id"),
    ("ix_automations_workspace_id", "automations", "workspace_id"),
    ("ix_automations_status", "automations", "status"),
    ("ix_workspace_files_workspace_id", "workspace_files", "workspace_id"),
    ("ix_workspace_files_automation_id", "workspace_files", "automation_id"),
    ("ix_workspace_files_status", "workspace_files", "status"),
    ("ix_workspace_files_content_sha256", "workspace_files", "content_sha256"),
    ("ix_workspace_files_detection_task_id", "workspace_files", "detection_task_id"),
    ("ix_agent_tasks_status", "agent_tasks", "status"),
    ("ix_agent_tasks_assigned_agent_id", "agent_tasks", "assigned_agent_id"),
    ("ix_schedules_automation_id", "schedules", "automation_id"),
    ("ix_schedules_status", "schedules", "status"),
    ("ix_schedules_next_run_at", "schedules", "next_run_at"),
    ("ix_execution_logs_automation_id", "execution_logs", "automation_id"),
    ("ix_execution_logs_task_id", "execution_logs", "task_id"),
    ("ix_execution_logs_created_at", "execution_logs", "created_at"),
    ("ix_execution_reports_status", "execution_reports", "status"),
    ("ix_execution_reports_source_task_id", "execution_reports", "source_task_id"),
]


def _existing_indexes(inspector, table: str) -> set[str]:
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for name, table, column in INDEXES:
        if table not in tables:
            continue
        if name not in _existing_indexes(inspector, table):
            op.create_index(name, table, [column])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for name, table, column in reversed(INDEXES):
        if table not in tables:
            continue
        if name in _existing_indexes(inspector, table):
            op.drop_index(name, table_name=table)
