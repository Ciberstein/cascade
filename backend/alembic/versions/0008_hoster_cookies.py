"""cookie jar for hosters that judge the caller

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # YouTube refuses requests coming from datacenter addresses - the same link
    # that works from a laptop answers "Sign in to confirm you're not a bot"
    # from a cloud host. A cookie jar authenticates the request, which is what
    # the block is actually asking for.
    #
    # It lives in the settings row rather than the environment so it can be
    # replaced from the running app: these expire every few weeks, and needing
    # a redeploy to paste a new one turns routine maintenance into an outage.
    op.add_column("settings", sa.Column("hoster_cookies", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "hoster_cookies")
