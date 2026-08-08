"""Access to the single-row `settings` table.

The row is the live source of truth for anything the user can change from the
Settings page. `Settings` (env vars) only supplies the values used before that
row exists - on a fresh install, or on any request that races the first write.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GlobalSettings

SETTINGS_ROW_ID = 1


async def read_settings(db: AsyncSession) -> GlobalSettings | None:
    """Returns the settings row, or None on a fresh install.

    Read-only on purpose: this runs on hot paths (every scheduler tick), and a
    tick has no business provisioning rows or committing on behalf of the API.
    Callers fall back to their env defaults when this returns None.
    """
    result = await db.execute(select(GlobalSettings).where(GlobalSettings.id == SETTINGS_ROW_ID))
    return result.scalar_one_or_none()


async def get_or_create_settings(db: AsyncSession) -> GlobalSettings:
    row = await read_settings(db)
    if row is not None:
        return row

    row = GlobalSettings(id=SETTINGS_ROW_ID)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # Two requests can reach the insert at once on a fresh install; the
        # loser reads back the winner's row instead of failing.
        await db.rollback()
        result = await db.execute(select(GlobalSettings).where(GlobalSettings.id == SETTINGS_ROW_ID))
        row = result.scalar_one()
    else:
        await db.refresh(row)
    return row
