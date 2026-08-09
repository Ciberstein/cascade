"""optional accounts that recover an owner token

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-09 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # La tabla vuelve, pero con otro propósito que la de Fase 1: no controla el
    # acceso, solo permite recuperar el owner_id desde otro dispositivo. De ahí
    # que owner_id sea único y que no haya sesiones ni tokens de acceso.
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('owner_id', sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('owner_id'),
    )
    op.create_index('ix_users_owner_id', 'users', ['owner_id'])


def downgrade() -> None:
    op.drop_index('ix_users_owner_id', table_name='users')
    op.drop_table('users')
