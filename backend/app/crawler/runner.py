"""Toma crawl_jobs pendientes y escribe sus resultados."""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.core import crawl_link
from app.models import CrawlJob, CrawlResult

logger = logging.getLogger(__name__)


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

    await asyncio.gather(*(_run_one_job(db, db_lock, job) for job in jobs))


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
                )
            )
        job.status = "done"
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
