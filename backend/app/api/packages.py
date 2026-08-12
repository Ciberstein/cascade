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
    """Where the server keeps what it downloads until the user retrieves it.

    It comes from the environment and not from the settings: the user receives
    their files through the browser, so this path is an infrastructure decision
    (which disk, which volume) and not something worth offering them.
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
        # The owner goes in the WHERE, not in a check afterwards: that way
        # another owner's id gives 404 rather than 403, and doesn't confirm
        # that the package exists.
        .where(Package.id == package_id, Package.owner_id == owner)
    )
    package = result.scalar_one_or_none()
    if package is None:
        raise HTTPException(status_code=404, detail="Package not found")

    if payload.status is not None:
        package.status = payload.status
    if payload.name is not None:
        # The visible name only. The folder on disk is NOT renamed: files
        # already downloaded live there, and moving them mid-download would
        # break the writes in flight.
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
    """Hands the file to the browser, which saves it wherever it saves all.

    Cascade downloads to the server's disk; the user's downloads folder is on
    their machine. This endpoint is the bridge: the browser fetches it from
    here with Content-Disposition, and it lands in their usual folder without
    anyone configuring a path.
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
        # Mid-download the file exists but is incomplete, and handing it over
        # would give a corrupt file that looks fine.
        raise HTTPException(status_code=409, detail="That download hasn't finished yet")

    path = _item_path(item)
    if item.file_removed_at is not None or not os.path.isfile(path):
        # El servidor es un lugar de paso: una vez retirado, el archivo se
        # libera. La fila queda en el historial, el archivo no.
        raise HTTPException(
            status_code=410,
            detail="The file is no longer on the server. Add the link again to fetch it once more.",
        )

    if item.retrieved_at is None:
        # First time only: the grace period counts from the first retrieval,
        # not the last, or retrying would postpone it forever.
        item.retrieved_at = dt.datetime.utcnow()
        await db.commit()

    # The delete runs as a background task: only once the response has
    # finished sending. If the browser cuts out midway it never runs and the
    # file stays for a retry - which is exactly what has to be preserved when
    # the download fires on its own and nobody is watching.
    return FileResponse(
        path,
        filename=item.filename,
        media_type="application/octet-stream",
        background=BackgroundTask(_release_after_delivery, path),
    )


def _release_after_delivery(path: str) -> None:
    """Frees the file as soon as the user has received it.

    It only touches the disk: marking the row would mean opening another
    session (the request's is already closed by the time this runs), and the
    sweep already reconciles missing files. Meanwhile the UI goes by
    `retrieved`, which was marked during the request.
    """
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("no se pudo liberar %s", path)


def _item_path(item: DownloadItem) -> str:
    """Path on disk, contained inside the package folder.

    Recomputed the same way the engine does rather than stored: that way the
    containment check applies here too, and a tampered row cannot make the
    server hand over a file from outside the package.
    """
    package_dir = item.package.target_dir
    return ensure_within(package_dir, os.path.join(package_dir, safe_filename(item.filename)))


@router.delete("/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_package(
    package_id: str,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    """Takes the package off the list and frees whatever is left on the server.

    It does delete the files, unlike a manager that keeps things: here the
    server is a place to pass through and the user's copy is on their machine.
    Leaving them would be exactly the accumulation this design avoids.
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
        # The engine has files open and would keep writing checkpoints over
        # rows that no longer exist.
        raise HTTPException(
            status_code=409,
            detail="Files are still downloading; pause or stop the package before removing it",
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
