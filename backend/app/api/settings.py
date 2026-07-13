from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import GlobalSettings, User
from app.schemas import SettingsResponse, UpdateSettingsRequest

router = APIRouter(prefix="/settings", tags=["settings"])


async def _get_or_create_settings(db: AsyncSession) -> GlobalSettings:
    result = await db.execute(select(GlobalSettings).where(GlobalSettings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = GlobalSettings(id=1)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return await _get_or_create_settings(db)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    payload: UpdateSettingsRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await _get_or_create_settings(db)
    row.download_root = payload.download_root
    row.max_concurrent_downloads = payload.max_concurrent_downloads
    row.chunks_per_file = payload.chunks_per_file
    row.max_speed_kbps = payload.max_speed_kbps
    await db.commit()
    await db.refresh(row)
    return row
