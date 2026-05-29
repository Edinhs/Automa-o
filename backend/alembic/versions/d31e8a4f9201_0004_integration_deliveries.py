"""0004_integration_deliveries

Revision ID: d31e8a4f9201
Revises: 2f4a6c8e9b11
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d31e8a4f9201"
down_revision: Union[str, None] = "2f4a6c8e9b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("delivery_type", sa.String(), nullable=True),
        sa.Column("target", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("request_json", sa.Text(), nullable=True),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_integration_deliveries_delivery_type"), "integration_deliveries", ["delivery_type"], unique=False)
    op.create_index(op.f("ix_integration_deliveries_id"), "integration_deliveries", ["id"], unique=False)
    op.create_index(op.f("ix_integration_deliveries_provider"), "integration_deliveries", ["provider"], unique=False)
    op.create_index(op.f("ix_integration_deliveries_status"), "integration_deliveries", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_integration_deliveries_status"), table_name="integration_deliveries")
    op.drop_index(op.f("ix_integration_deliveries_provider"), table_name="integration_deliveries")
    op.drop_index(op.f("ix_integration_deliveries_id"), table_name="integration_deliveries")
    op.drop_index(op.f("ix_integration_deliveries_delivery_type"), table_name="integration_deliveries")
    op.drop_table("integration_deliveries")
