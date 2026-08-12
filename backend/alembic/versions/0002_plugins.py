"""hoster plugins: crawl jobs, results, item hoster/retry_after, crawl concurrency

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('crawl_jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('raw_input', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('crawl_results',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('crawl_job_id', sa.String(length=36), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('filename', sa.String(length=1024), nullable=False),
    sa.Column('size', sa.Integer(), nullable=True),
    sa.Column('hoster', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['crawl_job_id'], ['crawl_jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # server_default en el add: las filas que ya existen necesitan un valor, y
    # todo lo descargado hasta ahora era un enlace directo.
    op.add_column('download_items', sa.Column('hoster', sa.String(length=64), nullable=False, server_default='direct'))
    op.add_column('download_items', sa.Column('retry_after', sa.DateTime(), nullable=True))
    op.add_column('settings', sa.Column('max_concurrent_crawls', sa.Integer(), nullable=False, server_default='5'))


def downgrade() -> None:
    op.drop_column('settings', 'max_concurrent_crawls')
    op.drop_column('download_items', 'retry_after')
    op.drop_column('download_items', 'hoster')
    op.drop_table('crawl_results')
    op.drop_table('crawl_jobs')
