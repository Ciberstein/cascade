"""drop the user-facing download folder setting

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-09 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # El usuario recibe sus archivos por el navegador, que los guarda donde
    # guarda todo. Dónde los deja el servidor mientras tanto sale de
    # DOWNLOAD_ROOT: es infraestructura, no un ajuste. Se borra la columna en
    # vez de dejarla sin leer, que es exactamente la clase de configuración
    # muerta que confunde después.
    op.drop_column('settings', 'download_root')


def downgrade() -> None:
    op.add_column(
        'settings',
        sa.Column('download_root', sa.String(length=1024), nullable=False, server_default='/downloads'),
    )
