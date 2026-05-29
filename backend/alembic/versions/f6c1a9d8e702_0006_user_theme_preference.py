"""0006_user_theme_preference

Revision ID: f6c1a9d8e702
Revises: e4a7c9d2b501
Create Date: 2026-05-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6c1a9d8e702"
down_revision: Union[str, None] = "e4a7c9d2b501"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("theme_preference", sa.String(), nullable=False, server_default="light")
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("theme_preference")
