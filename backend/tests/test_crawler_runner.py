import pytest
from sqlalchemy import select

from app.crawler.core import DiscoveredFile
from app.crawler.runner import run_pending_crawls
from app.models import CrawlJob, CrawlResult
from tests.conftest import TEST_OWNER


@pytest.fixture
def fake_crawl(monkeypatch):
    """Reemplaza crawl_link por un guion, para no tocar la red."""
    import app.crawler.runner as runner

    script: dict[str, list[DiscoveredFile] | Exception] = {}

    async def _crawl(url, **kwargs):
        outcome = script[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(runner, "crawl_link", _crawl)
    return script


def a_file(url="http://x/a.zip", name="a.zip", status="ok"):
    return DiscoveredFile(url=url, filename=name, size=7, hoster="direct", status=status, error_message=None)


@pytest.mark.asyncio
async def test_a_pending_job_becomes_done_with_its_results(session, fake_crawl):
    fake_crawl["http://x/a.zip"] = [a_file()]
    session.add(CrawlJob(raw_input="http://x/a.zip", owner_id=TEST_OWNER))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)

    job = (await session.execute(select(CrawlJob))).scalar_one()
    assert job.status == "done"
    results = (await session.execute(select(CrawlResult))).scalars().all()
    assert [r.filename for r in results] == ["a.zip"]
    assert results[0].hoster == "direct"


@pytest.mark.asyncio
async def test_every_line_of_the_paste_is_crawled(session, fake_crawl):
    fake_crawl["http://x/a"] = [a_file(url="http://x/a", name="a")]
    fake_crawl["http://x/b"] = [a_file(url="http://x/b", name="b")]
    session.add(CrawlJob(raw_input="http://x/a\n\n  http://x/b  \n", owner_id=TEST_OWNER))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)

    results = (await session.execute(select(CrawlResult))).scalars().all()
    assert sorted(r.filename for r in results) == ["a", "b"]


@pytest.mark.asyncio
async def test_one_bad_link_does_not_sink_the_whole_job(session, fake_crawl):
    fake_crawl["http://x/ok"] = [a_file(url="http://x/ok", name="ok")]
    fake_crawl["http://x/bad"] = RuntimeError("algo raro")
    session.add(CrawlJob(raw_input="http://x/ok\nhttp://x/bad", owner_id=TEST_OWNER))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)

    job = (await session.execute(select(CrawlJob))).scalar_one()
    assert job.status == "done"
    results = (await session.execute(select(CrawlResult))).scalars().all()
    by_name = {r.filename: r for r in results}
    assert by_name["ok"].status == "ok"
    assert by_name["bad"].status == "error"


@pytest.mark.asyncio
async def test_a_job_is_not_processed_twice(session, fake_crawl):
    calls = []

    async def counting(url, **kwargs):
        calls.append(url)
        return [a_file(url=url, name="x")]

    import app.crawler.runner as runner
    runner.crawl_link = counting

    session.add(CrawlJob(raw_input="http://x/a", owner_id=TEST_OWNER))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)
    await run_pending_crawls(session, max_concurrent=2)

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_only_max_concurrent_jobs_are_taken_per_pass(session, fake_crawl):
    for i in range(5):
        fake_crawl[f"http://x/{i}"] = [a_file(url=f"http://x/{i}", name=str(i))]
        session.add(CrawlJob(raw_input=f"http://x/{i}", owner_id=TEST_OWNER))
    await session.commit()

    await run_pending_crawls(session, max_concurrent=2)

    done = (await session.execute(select(CrawlJob).where(CrawlJob.status == "done"))).scalars().all()
    assert len(done) == 2
