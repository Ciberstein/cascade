"""a step to run once the bytes are down

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-12 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extracting the soundtrack downloads the audio track the site already
    # publishes for its higher qualities, then transcodes it. The transcode has
    # to survive a restart between the download finishing and ffmpeg running,
    # so what is pending is a column rather than something held in memory.
    op.add_column("download_items", sa.Column("postprocess", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("download_items", "postprocess")
