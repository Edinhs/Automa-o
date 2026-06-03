"""add_teams_integration

Revision ID: 0ec4c6ab1b99
Revises: b8e5f7a9c013
Create Date: 2026-06-02 19:55:44.109058

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ec4c6ab1b99'
down_revision: Union[str, None] = 'b8e5f7a9c013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'teams_channels' not in tables:
        op.create_table('teams_channels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('webhook_url', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_teams_channels_id'), 'teams_channels', ['id'], unique=False)
        op.create_index(op.f('ix_teams_channels_name'), 'teams_channels', ['name'], unique=False)

    if 'teams_report_schedules' not in tables:
        op.create_table('teams_report_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('report_type', sa.String(), nullable=False),
        sa.Column('file_format', sa.String(), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('frequency_type', sa.String(), nullable=False),
        sa.Column('run_date', sa.DateTime(), nullable=True),
        sa.Column('time_of_day', sa.String(), nullable=True),
        sa.Column('days_of_week', sa.String(), nullable=True),
        sa.Column('day_of_month', sa.Integer(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['channel_id'], ['teams_channels.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_teams_report_schedules_id'), 'teams_report_schedules', ['id'], unique=False)
        op.create_index(op.f('ix_teams_report_schedules_name'), 'teams_report_schedules', ['name'], unique=False)
        op.create_index(op.f('ix_teams_report_schedules_next_run_at'), 'teams_report_schedules', ['next_run_at'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'teams_report_schedules' in tables:
        op.drop_index(op.f('ix_teams_report_schedules_next_run_at'), table_name='teams_report_schedules')
        op.drop_index(op.f('ix_teams_report_schedules_name'), table_name='teams_report_schedules')
        op.drop_index(op.f('ix_teams_report_schedules_id'), table_name='teams_report_schedules')
        op.drop_table('teams_report_schedules')

    if 'teams_channels' in tables:
        op.drop_index(op.f('ix_teams_channels_name'), table_name='teams_channels')
        op.drop_index(op.f('ix_teams_channels_id'), table_name='teams_channels')
        op.drop_table('teams_channels')
