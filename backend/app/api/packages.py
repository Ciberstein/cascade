import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.owner import get_owner
from app.config import Settings
from app.database import get_db
from app.models import DownloadItem, Package
from app.schemas import CreatePackageRequest, PackageResponse, UpdatePackageRequest
from app.package_dirs import target_dir_for
from app.paths import ensure_within, safe_filename
from app.settings_store import read_settings

router = APIRouter(prefix="/packages", tags=["packages"])
_settings = Settings()


def _filename_from_url(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name or "download"


def _target_dir_root() -> str:
    """Dónde el servidor guarda lo que descarga, mientras el usuario lo retira.

    Sale del entorno y no de la configuración: el usuario recibe sus archivos
    por el navegador, así que esta ruta es una decisión de infraestructura
    (qué disco, qué volumen) y no algo que tenga sentido ofrecerle.
    """
    return _settings.download_root


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

    package.target_dir = await target_dir_for(db, _target_dir_root(), payload.name)

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


@router.get("/{package_id}/items/{item_id}/file")
async def download_item_file(
    package_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    """Entrega el archivo al navegador, que lo guarda donde guarda todo.

    Cascade descarga al disco del servidor; la carpeta de descargas del usuario
    está en su máquina. Este endpoint es el puente: el navegador se lo baja de
    acá con Content-Disposition, y termina en su carpeta de siempre sin que
    nadie tenga que configurar ninguna ruta.
    """
    result = await db.execute(
        select(DownloadItem)
        .join(Package)
        .where(
            DownloadItem.id == item_id,
            DownloadItem.package_id == package_id,
            Package.owner_id == owner,
        )
        .options(selectinload(DownloadItem.package))
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="File not found")

    if item.status != "completed":
        # A medio bajar el archivo existe pero está incompleto, y entregarlo
        # daría un archivo corrupto que parece bueno.
        raise HTTPException(status_code=409, detail="La descarga todavía no terminó")

    path = _item_path(item)
    if not os.path.isfile(path):
        # Alguien lo borró de la carpeta del servidor por fuera de Cascade.
        raise HTTPException(status_code=410, detail="El archivo ya no está en el servidor")

    return FileResponse(path, filename=item.filename, media_type="application/octet-stream")


def _item_path(item: DownloadItem) -> str:
    """Ruta en disco, contenida dentro de la carpeta del paquete.

    Se recalcula igual que en el motor en vez de guardarse: así el chequeo de
    contención se aplica también acá, y una fila manipulada no puede hacer que
    el servidor entregue un archivo de fuera del paquete.
    """
    package_dir = item.package.target_dir
    return ensure_within(package_dir, os.path.join(package_dir, safe_filename(item.filename)))


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
