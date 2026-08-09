"""Toma crawl_jobs pendientes y escribe sus resultados."""

import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.core import crawl_link
from app.models import CrawlJob, CrawlResult

logger = logging.getLogger(__name__)


async def requeue_stale_running_jobs(db: AsyncSession) -> None:
    """Devuelve a "pending" los jobs que un proceso anterior dejó en "running".

    La consulta de trabajo solo mira "pending", así que sin esto un reinicio a
    mitad de un crawl deja el job colgado para siempre y la bandeja mostrando
    "Buscando..." sin forma de distinguirlo de un crawl lento. Reencolarlo es
    seguro: crawlear no escribe nada fuera de crawl_results, y los resultados
    ya guardados se agregan a los que encuentre esta vez.
    """
    result = await db.execute(select(CrawlJob).where(CrawlJob.status == "running"))
    for job in result.scalars().all():
        job.status = "pending"
    await db.commit()


async def run_pending_crawls(db: AsyncSession, max_concurrent: int) -> None:
    """Procesa hasta `max_concurrent` jobs pendientes.

    Igual que run_pending del scheduler, comparte una sola sesión y serializa
    todo acceso a DB con un lock creado por llamada. Vale la misma
    precondición: hay que await-earla hasta el final antes de volver a
    llamarla contra la misma sesión.
    """
    db_lock = asyncio.Lock()

    result = await db.execute(
        select(CrawlJob).where(CrawlJob.status == "pending").limit(max_concurrent)
    )
    jobs = result.scalars().all()
    if not jobs:
        return

    async with db_lock:
        for job in jobs:
            job.status = "running"
        await db.commit()

    # return_exceptions=True a diferencia del scheduler: acá no hay motivo para
    # que un job aborte el lote. Sin esto, el primer fallo hace que gather
    # vuelva de inmediato, _crawl_tick cierra la sesión, y los jobs hermanos
    # siguen vivos escribiendo sobre una conexión ya devuelta al pool - la
    # misma corrupción de sesión compartida que Fase 1 existe para evitar.
    await asyncio.gather(*(_run_one_job(db, db_lock, job) for job in jobs), return_exceptions=True)


async def _run_one_job(db: AsyncSession, db_lock: asyncio.Lock, job: CrawlJob) -> None:
    links = [line.strip() for line in job.raw_input.splitlines() if line.strip()]
    discovered = []

    for link in links:
        try:
            discovered.extend(await crawl_link(link))
        except Exception as exc:  # noqa: BLE001 - un link malo no hunde el job
            # crawl_link ya absorbe los fallos de plugin; esto cubre lo que
            # ocurra fuera de ellos y evita que el gather aborte los otros jobs.
            logger.exception("crawl of %s failed", link)
            discovered.append(_error_row(link, str(exc)))

    try:
        async with db_lock:
            for found in discovered:
                db.add(
                    CrawlResult(
                        crawl_job_id=job.id,
                        url=found.url,
                        filename=found.filename,
                        size=found.size,
                        hoster=found.hoster,
                        status=found.status,
                        error_message=found.error_message,
                        # Como JSON y no como tabla: solo se leen enteras para
                        # pintar el selector, y se descartan al promover.
                        variants_json=json.dumps(
                            [
                                {
                                    "id": v.id,
                                    "label": v.label,
                                    "height": v.height,
                                    "size": v.size,
                                    "needs_merge": v.needs_merge,
                                    "video_format": v.video_format,
                                    "audio_format": v.audio_format,
                                }
                                for v in found.variants
                            ]
                        )
                        if found.variants
                        else None,
                    )
                )
            job.status = "done"
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - el job debe terminar en un estado final
        # Sin esto el job se queda en "running" para siempre: la consulta solo
        # levanta "pending" y nada lo reencola. La bandeja seguiría mostrando
        # "Buscando..." indefinidamente, sin forma de distinguirlo de un crawl
        # lento ni de limpiarlo. Un INSERT rechazado por Postgres (un tamaño
        # que no es entero, un filename más largo que la columna) llega acá.
        logger.exception("no se pudieron guardar los resultados del job %s", job.id)
        async with db_lock:
            await db.rollback()
            job.status = "error"
            job.error_message = str(exc)
            await db.commit()


def _error_row(url: str, message: str):
    from app.crawler.core import DiscoveredFile

    return DiscoveredFile(
        url=url,
        filename=url.rstrip("/").rsplit("/", 1)[-1] or url,
        size=None,
        hoster="direct",
        status="error",
        error_message=message,
    )
