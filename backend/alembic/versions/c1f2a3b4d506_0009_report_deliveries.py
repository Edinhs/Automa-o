"""0009_report_deliveries

Revision ID: c1f2a3b4d506
Revises: b8e5f7a9c013
Create Date: 2026-06-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1f2a3b4d506"
down_revision: Union[str, None] = "b8e5f7a9c013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("report_type", sa.String(), nullable=True),
        sa.Column("file_format", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("target", sa.String(), nullable=True),
        sa.Column("automation_id", sa.Integer(), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("period_days", sa.Integer(), nullable=True),
        sa.Column("frequency_type", sa.String(), nullable=True),
        sa.Column("time_of_day", sa.String(), nullable=True),
        sa.Column("days_of_week", sa.String(), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("run_date", sa.DateTime(), nullable=True),
        sa.Column("start_date", sa.DateTime(), nullable=True),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_delivery_id", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_report_deliveries_id"), "report_deliveries", ["id"], unique=False)
    op.create_index(op.f("ix_report_deliveries_name"), "report_deliveries", ["name"], unique=False)
    op.create_index(op.f("ix_report_deliveries_provider"), "report_deliveries", ["provider"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_report_deliveries_provider"), table_name="report_deliveries")
    op.drop_index(op.f("ix_report_deliveries_name"), table_name="report_deliveries")
    op.drop_index(op.f("ix_report_deliveries_id"), table_name="report_deliveries")
    op.drop_table("report_deliveries")
