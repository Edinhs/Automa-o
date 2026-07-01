"""0002_playwright_automation_contract

Revision ID: 8b9c2d4e6f10
Revises: 5e792e3007a6
Create Date: 2026-05-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8b9c2d4e6f10"
down_revision: Union[str, None] = "5e792e3007a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agent_tasks") as batch_op:
        batch_op.add_column(sa.Column("max_attempts", sa.Integer(), nullable=True))

    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.add_column(sa.Column("playground_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("add_data_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("data_languages", sa.String(), nullable=True))

    with op.batch_alter_table("workspace_files") as batch_op:
        batch_op.add_column(sa.Column("pdf_path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("playground_status", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("max_attempts", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("ready_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("failed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("manual_review_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("automations") as batch_op:
        batch_op.add_column(sa.Column("temp_folder_path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("batch_size", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("batch_interval_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("monitoring_timeout_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("monitor_interval_seconds", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("max_retries", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("keep_temp_on_error", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("convert_to_pdf_on_error", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("automations") as batch_op:
        batch_op.drop_column("convert_to_pdf_on_error")
        batch_op.drop_column("keep_temp_on_error")
        batch_op.drop_column("max_retries")
        batch_op.drop_column("monitor_interval_seconds")
        batch_op.drop_column("monitoring_timeout_minutes")
        batch_op.drop_column("batch_interval_seconds")
        batch_op.drop_column("batch_size")
        batch_op.drop_column("temp_folder_path")

    with op.batch_alter_table("workspace_files") as batch_op:
        batch_op.drop_column("manual_review_at")
        batch_op.drop_column("failed_at")
        batch_op.drop_column("ready_at")
        batch_op.drop_column("max_attempts")
        batch_op.drop_column("playground_status")
        batch_op.drop_column("pdf_path")

    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_column("data_languages")
        batch_op.drop_column("add_data_url")
        batch_op.drop_column("playground_url")

    with op.batch_alter_table("agent_tasks") as batch_op:
        batch_op.drop_column("max_attempts")
