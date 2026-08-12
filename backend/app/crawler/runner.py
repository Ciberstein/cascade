"""Takes pending crawl_jobs and writes their results."""

import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.core import crawl_link
from app.models import CrawlJob, CrawlResult

logger = logging.getLogger(__name__)


async def requeue_stale_running_jobs(db: AsyncSession) -> None:
    """Returns to "pending" the jobs a previous process left as "running".

    The work query only looks at "pending", so without this a restart midway
    through a crawl leaves the job hanging forever and the tray showing
    "Looking at..." with no way to tell it apart from a slow crawl. Requeueing
    is safe: crawling writes nothing outside crawl_results, and results already
    saved are added to whatever it finds this time round.
    """
    result = await db.execute(select(CrawlJob).where(CrawlJob.status == "running"))
    for job in result.scalars().all():
        job.status = "pending"
    await db.commit()


async def run_pending_crawls(db: AsyncSession, max_concurrent: int) -> None:
    """Processes up to `max_concurrent` pending jobs.

    Like the scheduler's run_pending, it shares a single session and serialises
    every DB access with a lock created per call. The same precondition holds:
    it must be awaited to completion before being called again against the same
    session.
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

    # return_exceptions=True, unlike the scheduler: there is no reason here for
    # one job to abort the batch. Without it the first failure makes gather
    # return immediately, _crawl_tick closes the session, and the sibling jobs
    # stay alive writing over a connection already returned to the pool - the
    # same shared-session corruption Phase 1 exists to avoid.
    await asyncio.gather(*(_run_one_job(db, db_lock, job) for job in jobs), return_exceptions=True)


async def _run_one_job(db: AsyncSession, db_lock: asyncio.Lock, job: CrawlJob) -> None:
    links = [line.strip() for line in job.raw_input.splitlines() if line.strip()]
    discovered = []

    for link in links:
        try:
            discovered.extend(await crawl_link(link))
        except Exception as exc:  # noqa: BLE001 - one bad link doesn't sink the job
            # crawl_link already absorbs plugin failures; this covers anything
            # happening outside them and stops gather aborting the other jobs.
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
                        # As JSON rather than a table: they are only ever read
                        # whole to paint the picker, and discarded on promotion.
                        variants_json=json.dumps(
                            [
                                {
                                    "id": v.id,
                                    "label": v.label,
                                    "height": v.height,
                                    "size": v.size,
                                    "needs_merge": v.needs_merge,
                                    "ext": v.ext,
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
    except Exception as exc:  # noqa: BLE001 - the job must reach a final state
        # Without this the job stays "running" forever: the query only picks up
        # "pending" and nothing requeues it. The tray would keep showing
        # "Looking at..." indefinitely, with no way to tell it apart from a slow
        # crawl nor to clear it. An INSERT rejected by Postgres (a size that
        # isn't an integer, a filename longer than the column) lands here.
        logger.exception("could not save the results of job %s", job.id)
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
