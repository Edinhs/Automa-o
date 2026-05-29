"""Add folder-monitoring provenance for files and reports.

Revision ID: b8e5f7a9c013
Revises: a7d4e6f8b902
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "b8e5f7a9c013"
down_revision = "a7d4e6f8b902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_files") as batch_op:
        batch_op.add_column(sa.Column("detection_source", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("detection_task_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("detection_classification", sa.String(), nullable=True))

    with op.batch_alter_table("execution_reports") as batch_op:
        batch_op.add_column(sa.Column("source_scope", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("generation_trigger", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("source_task_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("execution_reports") as batch_op:
        batch_op.drop_column("source_task_id")
        batch_op.drop_column("generation_trigger")
        batch_op.drop_column("source_scope")

    with op.batch_alter_table("workspace_files") as batch_op:
        batch_op.drop_column("detection_classification")
        batch_op.drop_column("detection_task_id")
        batch_op.drop_column("detection_source")
