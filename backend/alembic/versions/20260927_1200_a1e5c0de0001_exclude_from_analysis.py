"""transactions.exclude_from_analysis

Revision ID: a1e5c0de0001
Revises: 0c87c4d9854b
Create Date: 2026-09-27 12:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1e5c0de0001'
down_revision: Union[str, None] = '0c87c4d9854b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('exclude_from_analysis', sa.Boolean(), server_default='0', nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_column('exclude_from_analysis')
