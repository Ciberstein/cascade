import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.config import Settings
from app.database import get_db
from app.models import CrawlJob, CrawlResult, DownloadItem, Package, User
from app.schemas import CrawlJobResponse, CreateCrawlJobRequest, PackageResponse, PromoteRequest
from app.settings_store import read_settings

router = APIRouter(prefix="/crawl-jobs", tags=["crawl"])
_settings = Settings()


@router.post("", response_model=CrawlJobResponse, status_code=status.HTTP_201_CREATED)
async def create_crawl_job(
    payload: CreateCrawlJobRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    job = CrawlJob(raw_input=payload.links)
    db.add(job)
    await db.commit()

    result = await db.execute(
        select(CrawlJob).options(selectinload(CrawlJob.results)).where(CrawlJob.id == job.id)
    )
    return result.scalar_one()


@router.get("", response_model=list[CrawlJobResponse])
async def list_crawl_jobs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CrawlJob).options(selectinload(CrawlJob.results)).order_by(CrawlJob.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{job_id}", response_model=CrawlJobResponse)
async def get_crawl_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(CrawlJob).options(selectinload(CrawlJob.results)).where(CrawlJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return job


@router.post("/{job_id}/promote", response_model=PackageResponse, status_code=status.HTTP_201_CREATED)
async def promote(
    job_id: str,
    payload: PromoteRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Convierte los resultados elegidos en un paquete descargable.

    La copia es deliberada: los crawl_results son un hallazgo, los
    download_items son trabajo comprometido. Mantenerlos separados es lo que
    deja al scheduler con su contrato simple ("un item en queued es algo para
    bajar") en vez de tener que filtrar filas a medio resolver.
    """
    result = await db.execute(
        select(CrawlResult).where(
            CrawlResult.crawl_job_id == job_id,
            CrawlResult.id.in_(payload.result_ids),
            # La UI ya deshabilita las casillas de los muertos, pero eso es
            # presentación: sin filtrar acá, un cliente puede encolar un item
            # cuyo fallo está garantizado.
            CrawlResult.status == "ok",
        )
    )
    chosen = result.scalars().all()
    if not chosen:
        raise HTTPException(status_code=404, detail="No matching crawl results")

    root = await _download_root(db)
    package = Package(name=payload.name, status="queued", target_dir="")
    db.add(package)
    await db.flush()  # populates package.id
    package.target_dir = os.path.join(root, package.id)

    taken: set[str] = set()
    for found in chosen:
        db.add(
            DownloadItem(
                package_id=package.id,
                url=found.url,
                # El crawler aplana el árbol: "media/notes.txt" y
                # "media/sub/notes.txt" llegan acá con el mismo nombre y van a
                # la misma carpeta. Sin desambiguar serían dos items con el
                # mismo destino, y el scheduler los correría a la vez: dos
                # escritores abriendo el mismo archivo en "r+b" y buscando sus
                # propios rangos. El resultado es un archivo con las dos
                # descargas entremezcladas y ambos items en "completed".
                filename=_unique_filename(found.filename, taken),
                total_size=found.size,
                hoster=found.hoster,
                status="queued",
            )
        )

    await db.commit()

    created = await db.execute(
        select(Package).options(selectinload(Package.items)).where(Package.id == package.id)
    )
    return created.scalar_one()


def _unique_filename(name: str, taken: set[str]) -> str:
    """Agrega un sufijo numérico si el nombre ya se usó en este paquete."""
    if name not in taken:
        taken.add(name)
        return name

    stem, dot, ext = name.partition(".")
    for n in range(2, 1000):
        candidate = f"{stem} ({n}){dot}{ext}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise HTTPException(status_code=409, detail=f"demasiados archivos llamados {name}")


async def _download_root(db: AsyncSession) -> str:
    row = await read_settings(db)
    return row.download_root if row is not None else _settings.download_root
