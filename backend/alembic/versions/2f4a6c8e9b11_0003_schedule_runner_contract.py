"""0003_schedule_runner_contract

Revision ID: 2f4a6c8e9b11
Revises: 8b9c2d4e6f10
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2f4a6c8e9b11"
down_revision: Union[str, None] = "8b9c2d4e6f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("schedules") as batch_op:
        batch_op.add_column(sa.Column("interval_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("next_run_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_run_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_task_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("schedules") as batch_op:
        batch_op.drop_column("last_error")
        batch_op.drop_column("last_task_id")
        batch_op.drop_column("last_run_at")
        batch_op.drop_column("next_run_at")
        batch_op.drop_column("interval_minutes")
