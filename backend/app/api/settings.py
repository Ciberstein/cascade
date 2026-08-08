from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import SettingsResponse, UpdateSettingsRequest
from app.settings_store import get_or_create_settings as _get_or_create_settings

router = APIRouter(prefix="/settings", tags=["settings"])


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
    row.max_concurrent_crawls = payload.max_concurrent_crawls
    await db.commit()
    await db.refresh(row)
    return row
