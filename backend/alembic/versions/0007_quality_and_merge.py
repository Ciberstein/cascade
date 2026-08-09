"""user-chosen quality, merging separate tracks

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-09 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Las calidades altas de los sitios grandes vienen en pistas separadas:
    # YouTube publica 33 formatos y solo el de 360p trae video y audio juntos.
    # Sin poder unirlas, elegir calidad no tendría nada que elegir.
    op.add_column('download_items', sa.Column('format_id', sa.String(length=64), nullable=True))
    op.add_column('download_items', sa.Column('merge_group', sa.String(length=36), nullable=True))
    op.add_column('download_items', sa.Column('merge_role', sa.String(length=10), nullable=True))
    op.create_index('ix_download_items_merge_group', 'download_items', ['merge_group'])
    # Las calidades ofrecidas viajan como JSON: solo se leen enteras para
    # pintar el selector y se descartan al promover.
    op.add_column('crawl_results', sa.Column('variants_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('crawl_results', 'variants_json')
    op.drop_index('ix_download_items_merge_group', table_name='download_items')
    op.drop_column('download_items', 'merge_role')
    op.drop_column('download_items', 'merge_group')
    op.drop_column('download_items', 'format_id')
