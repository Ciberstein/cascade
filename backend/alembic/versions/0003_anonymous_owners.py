"""anonymous browser owners, no accounts

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Dueño que se asigna a lo que ya existía antes de que hubiera dueños. Es un
#: token que ningún navegador va a generar, así que ese historial queda
#: archivado en vez de aparecerle a la primera persona que entre.
_LEGACY_OWNER = "legacy0000000000000000000000000000"


def upgrade() -> None:
    # server_default para las filas existentes; se quita después para que toda
    # fila nueva esté obligada a traer su dueño.
    op.add_column(
        'packages',
        sa.Column('owner_id', sa.String(length=128), nullable=False, server_default=_LEGACY_OWNER),
    )
    op.add_column(
        'crawl_jobs',
        sa.Column('owner_id', sa.String(length=128), nullable=False, server_default=_LEGACY_OWNER),
    )
    op.alter_column('packages', 'owner_id', server_default=None)
    op.alter_column('crawl_jobs', 'owner_id', server_default=None)

    op.create_index('ix_packages_owner_id', 'packages', ['owner_id'])
    op.create_index('ix_crawl_jobs_owner_id', 'crawl_jobs', ['owner_id'])

    # Ya no hay cuentas. Cuando existan, su diseño será otro (el token anónimo
    # que se puede recuperar desde otro dispositivo), así que esta tabla no
    # sirve de base para nada.
    op.drop_table('users')


def downgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )
    op.drop_index('ix_crawl_jobs_owner_id', table_name='crawl_jobs')
    op.drop_index('ix_packages_owner_id', table_name='packages')
    op.drop_column('crawl_jobs', 'owner_id')
    op.drop_column('packages', 'owner_id')
