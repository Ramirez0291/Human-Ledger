"""budgets: default (year_month NULL) + special_budgets

Revision ID: b0d9e7a10002
Revises: a1e5c0de0001
Create Date: 2026-09-29 10:00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b0d9e7a10002'
down_revision: Union[str, None] = 'a1e5c0de0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('budgets', schema=None) as batch_op:
        batch_op.alter_column('year_month', existing_type=sa.String(length=7), nullable=True)

    op.create_table(
        'special_budgets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('kind', sa.Enum('holiday', 'bonus', 'treat', 'other', name='special_budget_kind', native_enum=False), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=False),
        sa.Column('date_to', sa.Date(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('memo', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_special_budgets_category_id_categories'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_special_budgets_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_special_budgets')),
    )
    with op.batch_alter_table('special_budgets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_special_budgets_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('special_budgets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_special_budgets_user_id'))
    op.drop_table('special_budgets')
    op.execute("DELETE FROM budgets WHERE year_month IS NULL")
    with op.batch_alter_table('budgets', schema=None) as batch_op:
        batch_op.alter_column('year_month', existing_type=sa.String(length=7), nullable=False)
