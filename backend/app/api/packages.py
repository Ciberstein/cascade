import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.owner import get_owner
from app.config import Settings
from app.database import get_db
from app.models import DownloadItem, Package
from app.schemas import CreatePackageRequest, PackageResponse, UpdatePackageRequest
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
async def update_package(
    package_id: str,
    payload: UpdatePackageRequest,
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

    if payload.status is not None:
        package.status = payload.status
    if payload.name is not None:
        # Solo el nombre visible. La carpeta en disco NO se renombra: los
        # archivos ya bajados viven ahí, y moverlos a mitad de una descarga
        # rompería las escrituras en curso.
        package.name = payload.name

    await db.commit()
    await db.refresh(package, attribute_names=["items"])
    return package


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_package(
    package_id: str,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    """Saca el paquete de la lista.

    Los archivos ya descargados **no** se borran: quedan en la carpeta, igual
    que cuando un navegador borra una descarga de su historial. Borrar el
    trabajo terminado de alguien porque quiso limpiar su lista sería una
    sorpresa cara y sin vuelta atrás.
    """
    result = await db.execute(
        select(Package)
        .options(selectinload(Package.items))
        .where(Package.id == package_id, Package.owner_id == owner)
    )
    package = result.scalar_one_or_none()
    if package is None:
        raise HTTPException(status_code=404, detail="Package not found")

    if any(i.status == "running" for i in package.items):
        # El motor tiene archivos abiertos y va a seguir escribiendo checkpoints
        # sobre filas que ya no existirían.
        raise HTTPException(
            status_code=409,
            detail="Hay archivos descargando; pausá o cancelá el paquete antes de eliminarlo",
        )

    await db.delete(package)
    await db.commit()
