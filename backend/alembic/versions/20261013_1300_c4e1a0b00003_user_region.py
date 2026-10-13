"""users.region: region pack (currency / timezone / seed categories)

Revision ID: c4e1a0b00003
Revises: b0d9e7a10002
Create Date: 2026-10-13 13:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e1a0b00003'
down_revision: Union[str, None] = 'b0d9e7a10002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing users all keep yen ledgers: integer amounts stay valid as-is.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('region', sa.String(length=8), server_default='JP', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('region')
