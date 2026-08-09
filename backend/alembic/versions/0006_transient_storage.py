"""the server is a waypoint: track retrieval so files can be freed

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-09 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # El servidor deja de acumular: guarda el archivo solo hasta que el usuario
    # lo retira. Estas dos marcas son lo que le permite al barrido saber qué
    # puede borrar sin perder el historial, que sí se conserva.
    op.add_column('download_items', sa.Column('retrieved_at', sa.DateTime(), nullable=True))
    op.add_column('download_items', sa.Column('file_removed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('download_items', 'file_removed_at')
    op.drop_column('download_items', 'retrieved_at')
