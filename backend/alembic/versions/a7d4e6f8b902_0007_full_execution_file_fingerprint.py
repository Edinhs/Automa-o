"""0007_full_execution_file_fingerprint

Revision ID: a7d4e6f8b902
Revises: f6c1a9d8e702
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7d4e6f8b902"
down_revision: Union[str, None] = "f6c1a9d8e702"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("automations") as batch_op:
        batch_op.add_column(sa.Column("full_execution", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("workspace_files") as batch_op:
        batch_op.add_column(sa.Column("content_sha256", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace_files") as batch_op:
        batch_op.drop_column("content_sha256")

    with op.batch_alter_table("automations") as batch_op:
        batch_op.drop_column("full_execution")
