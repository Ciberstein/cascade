import datetime as dt

import pytest
from sqlalchemy import select

from app.models import CrawlJob, CrawlResult, DownloadItem, GlobalSettings, Package
from tests.conftest import TEST_OWNER


@pytest.mark.asyncio
async def test_crawl_job_holds_the_raw_pasted_text(session):
    job = CrawlJob(raw_input="http://a/x\nhttp://b/y", owner_id=TEST_OWNER)
    session.add(job)
    await session.commit()

    stored = (await session.execute(select(CrawlJob))).scalar_one()
    assert stored.status == "pending"
    assert stored.raw_input.splitlines() == ["http://a/x", "http://b/y"]
    assert stored.created_at is not None


@pytest.mark.asyncio
async def test_crawl_results_hang_off_their_job(session):
    job = CrawlJob(raw_input="http://a/x", owner_id=TEST_OWNER)
    session.add(job)
    await session.flush()
    session.add(
        CrawlResult(
            crawl_job_id=job.id, url="http://a/x", filename="x.zip", size=10, hoster="direct", status="ok"
        )
    )
    await session.commit()

    stored = (await session.execute(select(CrawlResult))).scalar_one()
    assert stored.crawl_job_id == job.id
    assert stored.status == "ok"


@pytest.mark.asyncio
async def test_download_items_record_their_hoster_and_have_no_wait_by_default(session, tmp_path):
    package = Package(name="p", status="queued", target_dir=str(tmp_path), owner_id=TEST_OWNER)
    session.add(package)
    await session.flush()
    item = DownloadItem(package_id=package.id, url="http://a/x", filename="x", hoster="direct")
    session.add(item)
    await session.commit()

    stored = (await session.execute(select(DownloadItem))).scalar_one()
    assert stored.hoster == "direct"
    # Sin espera pendiente el scheduler lo levanta de inmediato; ese es el caso normal.
    assert stored.retry_after is None


@pytest.mark.asyncio
async def test_settings_carry_a_crawl_concurrency_limit(session):
    session.add(GlobalSettings(id=1))
    await session.commit()

    row = (await session.execute(select(GlobalSettings))).scalar_one()
    # Más alto que el de descargas: crawlear es esperar respuestas cortas y no
    # satura ni disco ni ancho de banda.
    assert row.max_concurrent_crawls == 5
