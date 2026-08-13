from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.owner import get_owner
from app.database import get_db
from app.schemas import SettingsResponse, UpdateSettingsRequest
from app.settings_store import get_or_create_settings as _get_or_create_settings

router = APIRouter(prefix="/settings", tags=["settings"])

# CAREFUL: these settings are GLOBAL to the server, not per owner. The engine
# limits are an operator's decision, and today anyone who shows up can change
# them for everybody. That is acceptable on a private instance and is a known
# blocker for public use: there they have to become read-only or sit behind an
# operator token.


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db), owner: str = Depends(get_owner)):
    return await _get_or_create_settings(db)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    payload: UpdateSettingsRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    row = await _get_or_create_settings(db)
    row.max_concurrent_downloads = payload.max_concurrent_downloads
    row.chunks_per_file = payload.chunks_per_file
    row.max_speed_kbps = payload.max_speed_kbps
    row.max_concurrent_crawls = payload.max_concurrent_crawls
    if payload.hoster_cookies is not None:
        # Empty string clears it; None means the client said nothing about
        # cookies and the stored jar stays as it is.
        row.hoster_cookies = payload.hoster_cookies.strip() or None
    await db.commit()
    await db.refresh(row)
    return row
