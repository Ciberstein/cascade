import datetime as dt
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
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

logger = logging.getLogger(__name__)

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
    if item.file_removed_at is not None or not os.path.isfile(path):
        # El servidor es un lugar de paso: una vez retirado, el archivo se
        # libera. La fila queda en el historial, el archivo no.
        raise HTTPException(
            status_code=410,
            detail="El archivo ya no está en el servidor. Volvé a agregar el enlace para bajarlo otra vez.",
        )

    if item.retrieved_at is None:
        # Solo la primera vez: el margen de gracia se cuenta desde el primer
        # retiro, no desde el último, o reintentar lo postergaría sin fin.
        item.retrieved_at = dt.datetime.utcnow()
        await db.commit()

    # El borrado va como tarea de fondo: corre recién cuando la respuesta
    # terminó de enviarse. Si el navegador corta a mitad, no llega a correr y
    # el archivo queda para reintentar - que es justo lo que hay que preservar
    # cuando la descarga se dispara sola y nadie está mirando.
    return FileResponse(
        path,
        filename=item.filename,
        media_type="application/octet-stream",
        background=BackgroundTask(_release_after_delivery, path),
    )


def _release_after_delivery(path: str) -> None:
    """Libera el archivo apenas el usuario lo recibió.

    Solo toca el disco: marcar la fila exigiría abrir otra sesión (la de la
    request ya se cerró cuando esto corre), y el barrido ya reconcilia los
    archivos que faltan. Mientras tanto la UI se guía por `retrieved`, que sí
    se marcó durante la request.
    """
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("no se pudo liberar %s", path)


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
    """Saca el paquete de la lista y libera lo que quede en el servidor.

    Sí borra los archivos, a diferencia de lo que haría un gestor que guarda:
    acá el servidor es un lugar de paso y la copia del usuario está en su
    equipo. Dejarlos sería exactamente la acumulación que se quiere evitar.
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

    for item in package.items:
        if item.file_removed_at is not None:
            continue
        try:
            os.remove(os.path.join(package.target_dir, item.filename))
        except FileNotFoundError:
            pass
        except OSError:
            # No poder borrar un archivo no puede impedir sacar el paquete de
            # la lista; el barrido lo va a reintentar.
            logger.exception("no se pudo liberar %s", item.filename)

    await db.delete(package)
    await db.commit()
