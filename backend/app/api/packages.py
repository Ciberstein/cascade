import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.owner import get_owner
from app.config import Settings
from app.database import get_db
from app.models import DownloadItem, Package
from app.schemas import CreatePackageRequest, PackageResponse, UpdatePackageStatusRequest
from app.package_dirs import target_dir_for
from app.settings_store import read_settings

router = APIRouter(prefix="/packages", tags=["packages"])
_settings = Settings()


def _filename_from_url(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name or "download"


async def _target_dir_root(db: AsyncSession) -> str:
    """Where new packages are stored, preferring the user's saved setting.

    Resolved per request, not at import: otherwise the "Carpeta de descarga"
    field would persist a value that nothing ever reads. Existing packages
    keep the target_dir they were created with - moving files already on disk
    is not something a settings change should do behind the user's back.
    """
    row = await read_settings(db)
    return row.download_root if row is not None else _settings.download_root


@router.get("", response_model=list[PackageResponse])
async def list_packages(
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    result = await db.execute(
        select(Package).options(selectinload(Package.items)).where(Package.owner_id == owner)
    )
    return result.scalars().all()


@router.post("", response_model=PackageResponse, status_code=status.HTTP_201_CREATED)
async def create_package(
    payload: CreatePackageRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    package = Package(name=payload.name, status="queued", target_dir="", owner_id=owner)
    db.add(package)
    await db.flush()  # populates package.id

    package.target_dir = await target_dir_for(db, await _target_dir_root(db), payload.name)

    for url in payload.urls:
        db.add(
            DownloadItem(
                package_id=package.id,
                url=url,
                filename=_filename_from_url(url),
                status="queued",
                hoster="direct",
            )
        )

    await db.commit()

    result = await db.execute(
        select(Package).options(selectinload(Package.items)).where(Package.id == package.id)
    )
    return result.scalar_one()


@router.patch("/{package_id}", response_model=PackageResponse)
async def update_package_status(
    package_id: str,
    payload: UpdatePackageStatusRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    result = await db.execute(
        select(Package)
        .options(selectinload(Package.items))
        # El dueño va en el WHERE, no en un chequeo posterior: así un id de otro
        # dueño da 404 en vez de 403, y no confirma que ese paquete exista.
        .where(Package.id == package_id, Package.owner_id == owner)
    )
    package = result.scalar_one_or_none()
    if package is None:
        raise HTTPException(status_code=404, detail="Package not found")

    package.status = payload.status
    await db.commit()
    await db.refresh(package, attribute_names=["items"])
    return package
