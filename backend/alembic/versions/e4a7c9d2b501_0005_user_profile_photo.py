"""0005_user_profile_photo

Revision ID: e4a7c9d2b501
Revises: d31e8a4f9201
Create Date: 2026-05-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4a7c9d2b501"
down_revision: Union[str, None] = "d31e8a4f9201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("profile_photo_path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("profile_photo_mime_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("profile_photo_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("profile_photo_updated_at")
        batch_op.drop_column("profile_photo_mime_type")
        batch_op.drop_column("profile_photo_path")
