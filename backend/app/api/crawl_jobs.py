import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.owner import get_owner
from app.config import Settings
from app.database import get_db
from app.models import CrawlJob, CrawlResult, DownloadItem, Package
from app.schemas import CrawlJobResponse, CreateCrawlJobRequest, PackageResponse, PromoteRequest
from app.package_dirs import target_dir_for
from app.paths import unique_name

router = APIRouter(prefix="/crawl-jobs", tags=["crawl"])
_settings = Settings()


@router.post("", response_model=CrawlJobResponse, status_code=status.HTTP_201_CREATED)
async def create_crawl_job(
    payload: CreateCrawlJobRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    job = CrawlJob(raw_input=payload.links, owner_id=owner)
    db.add(job)
    await db.commit()

    result = await db.execute(
        select(CrawlJob).options(selectinload(CrawlJob.results)).where(CrawlJob.id == job.id)
    )
    return result.scalar_one()


@router.get("", response_model=list[CrawlJobResponse])
async def list_crawl_jobs(
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    result = await db.execute(
        select(CrawlJob)
        .options(selectinload(CrawlJob.results))
        .where(CrawlJob.owner_id == owner)
        .order_by(CrawlJob.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{job_id}", response_model=CrawlJobResponse)
async def get_crawl_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    result = await db.execute(
        select(CrawlJob)
        .options(selectinload(CrawlJob.results))
        .where(CrawlJob.id == job_id, CrawlJob.owner_id == owner)
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
    owner: str = Depends(get_owner),
):
    """Convierte los resultados elegidos en un paquete descargable.

    La copia es deliberada: los crawl_results son un hallazgo, los
    download_items son trabajo comprometido. Mantenerlos separados es lo que
    deja al scheduler con su contrato simple ("un item en queued es algo para
    bajar") en vez de tener que filtrar filas a medio resolver.
    """
    owned = await db.execute(
        select(CrawlJob.id).where(CrawlJob.id == job_id, CrawlJob.owner_id == owner)
    )
    if owned.scalar_one_or_none() is None:
        # Sin esto, conociendo un id de job ajeno se podrían promover sus
        # resultados al paquete propio.
        raise HTTPException(status_code=404, detail="Crawl job not found")

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

    root = _download_root()
    package = Package(name=payload.name, status="queued", target_dir="", owner_id=owner)
    db.add(package)
    await db.flush()  # populates package.id
    package.target_dir = await target_dir_for(db, root, payload.name)

    taken: set[str] = set()
    for found in chosen:
        variant = _chosen_variant(found, payload.quality.get(found.id))
        filename = unique_name(found.filename, taken)

        if variant and variant.get("needs_merge"):
            # Esta calidad viene en pistas separadas: se encolan las dos y el
            # motor las une al terminar. El audio no se le muestra al usuario -
            # es un medio, no una descarga que él pidió.
            group = uuid.uuid4().hex
            db.add(
                DownloadItem(
                    package_id=package.id, url=found.url, filename=filename,
                    total_size=None, hoster=found.hoster, status="queued",
                    format_id=variant["video_format"], merge_group=group, merge_role="video",
                )
            )
            db.add(
                DownloadItem(
                    package_id=package.id, url=found.url, filename=filename,
                    total_size=None, hoster=found.hoster, status="queued",
                    format_id=variant["audio_format"], merge_group=group, merge_role="audio",
                )
            )
            continue

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
                filename=filename,
                total_size=variant.get("size") if variant else found.size,
                hoster=found.hoster,
                status="queued",
                format_id=variant["video_format"] if variant else None,
            )
        )

    await db.commit()

    created = await db.execute(
        select(Package).options(selectinload(Package.items)).where(Package.id == package.id)
    )
    return created.scalar_one()



def _chosen_variant(found, variant_id: str | None) -> dict | None:
    """La calidad elegida, o la mejor disponible si el cliente no eligió.

    Las variantes vienen ordenadas de mejor a peor, así que la primera es el
    default sensato: quien no elige espera la mejor. Un id que ya no existe
    cae en ese mismo default en vez de fallar la promoción entera.
    """
    variants = found.variants
    if not variants:
        return None
    if variant_id is None:
        return variants[0]
    return next((v for v in variants if v["id"] == variant_id), variants[0])


def _download_root() -> str:
    """Ver _target_dir_root en api/packages.py: es infraestructura, no ajuste."""
    return _settings.download_root
