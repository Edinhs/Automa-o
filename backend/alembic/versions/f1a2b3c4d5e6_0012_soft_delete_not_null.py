"""0012 is_deleted NOT NULL (server_default false) + indice de dedup em workspace_files

Revision ID: f1a2b3c4d5e6
Revises: e7b3d5a9c528
Create Date: 2026-07-02

Corrige o drift em que is_deleted era nullable=True no schema: uma linha com is_deleted IS NULL
ficava INVISIVEL para todas as consultas ativas (SQL: NULL == False nunca e verdadeiro) e tambem
para o trash/restore -- um "limbo" de dados. Faz backfill de NULL -> FALSE e torna a coluna
NOT NULL com server_default FALSE em todas as tabelas de soft-delete. Idempotente (checa o schema
antes de agir), no estilo defensivo das migracoes 0009-0011.

Tambem cria um indice parcial de dedup em workspace_files(automation_id, content_sha256) apenas
para linhas ativas com hash -- rede de seguranca contra bugs futuros de dedup (hoje feito na
aplicacao). UNIQUE quando nao ha duplicata existente; senao cria NAO-unico (ainda acelera a query
de baseline) para NUNCA falhar a migracao em bancos com dados legados.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "f1a2b3c4d5e6"
down_revision = "e7b3d5a9c528"
branch_labels = None
depends_on = None


# Todas as tabelas candidatas a soft-delete. O guard _has_column pula as que nao tiverem a coluna
# (ex.: execution_logs / integration_connections), entao a lista pode ser abrangente com seguranca.
_SOFT_DELETE_TABLES = [
    "users",
    "workspaces",
    "automations",
    "workspace_files",
    "agent_tasks",
    "local_agents",
    "execution_reports",
    "integration_connections",
    "integration_deliveries",
    "workspace_external_users",
    "schedules",
]
_DEDUP_INDEX = "ix_workspace_files_dedup"


def _tables(bind):
    return set(inspect(bind).get_table_names())


def _columns(bind, table):
    return {c["name"]: c for c in inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    for table in _SOFT_DELETE_TABLES:
        if table not in tables:
            continue
        columns = _columns(bind, table)
        if "is_deleted" not in columns:
            continue
        # Backfill antes do NOT NULL (FALSE e aceito por SQLite >= 3.23 e por Postgres).
        op.execute(sa.text(f"UPDATE {table} SET is_deleted = FALSE WHERE is_deleted IS NULL"))
        if columns["is_deleted"].get("nullable", True):
            with op.batch_alter_table(table) as batch:
                batch.alter_column(
                    "is_deleted",
                    existing_type=sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )

    # Indice de dedup (apos o backfill/NOT NULL, todas as linhas tem is_deleted definido).
    if "workspace_files" in tables:
        wf_columns = _columns(bind, "workspace_files")
        indexes = {ix["name"] for ix in inspect(bind).get_indexes("workspace_files")}
        if "content_sha256" in wf_columns and _DEDUP_INDEX not in indexes:
            duplicates = bind.execute(
                sa.text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT automation_id, content_sha256 FROM workspace_files "
                    "WHERE is_deleted = FALSE AND content_sha256 IS NOT NULL "
                    "GROUP BY automation_id, content_sha256 HAVING COUNT(*) > 1"
                    ") AS dups"
                )
            ).scalar()
            op.create_index(
                _DEDUP_INDEX,
                "workspace_files",
                ["automation_id", "content_sha256"],
                unique=(not duplicates),
                sqlite_where=sa.text("is_deleted = FALSE AND content_sha256 IS NOT NULL"),
                postgresql_where=sa.text("is_deleted = FALSE AND content_sha256 IS NOT NULL"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    if "workspace_files" in tables:
        indexes = {ix["name"] for ix in inspect(bind).get_indexes("workspace_files")}
        if _DEDUP_INDEX in indexes:
            op.drop_index(_DEDUP_INDEX, table_name="workspace_files")
    for table in _SOFT_DELETE_TABLES:
        if table not in tables:
            continue
        columns = _columns(bind, table)
        if "is_deleted" not in columns or columns["is_deleted"].get("nullable", True):
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "is_deleted",
                existing_type=sa.Boolean(),
                nullable=True,
                server_default=None,
            )
