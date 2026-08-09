from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.owner import get_owner
from app.database import get_db
from app.schemas import SettingsResponse, UpdateSettingsRequest
from app.settings_store import get_or_create_settings as _get_or_create_settings

router = APIRouter(prefix="/settings", tags=["settings"])

# OJO: esta configuración es GLOBAL del servidor, no por dueño. La carpeta de
# descarga y los límites del motor son decisiones del operador, y hoy cualquiera
# que llegue puede cambiarlas para todos. Es aceptable en una instancia propia y
# es un bloqueante conocido para el uso público: ahí tienen que pasar a ser
# solo-lectura o quedar detrás de un token de operador.


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
    await db.commit()
    await db.refresh(row)
    return row
