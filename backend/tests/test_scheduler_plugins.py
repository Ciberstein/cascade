import datetime as dt

import pytest
from sqlalchemy import select

from app.engine.scheduler import run_pending
from app.models import DownloadItem, Package
from app.plugins.base import DirectLink, LinkDead, RateLimited


async def one_item(session, tmp_path, url, **item_kwargs):
    package = Package(name="pkg", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    item = DownloadItem(
        package_id=package.id, url=url, filename="out.bin", status="queued",
        hoster="fake", **item_kwargs
    )
    session.add(item)
    await session.commit()
    return item


@pytest.mark.asyncio
async def test_the_resolver_supplies_the_url_that_is_actually_downloaded(session, test_server, tmp_path):
    payload = b"R" * 300
    _, real_url = await test_server(payload)
    item = await one_item(session, tmp_path, "http://placeholder/hidden")

    async def resolver(url, hoster):
        assert url == "http://placeholder/hidden"
        assert hoster == "fake"
        return DirectLink(url=real_url)

    await run_pending(session, max_concurrent=1, chunks_per_file=2, resolver=resolver)

    await session.refresh(item)
    assert item.status == "completed"
    assert (tmp_path / "out.bin").read_bytes() == payload


@pytest.mark.asyncio
async def test_a_rate_limited_item_is_rescheduled_not_failed(session, test_server, tmp_path):
    item = await one_item(session, tmp_path, "http://x/a")
    when = dt.datetime.utcnow() + dt.timedelta(minutes=30)

    async def resolver(url, hoster):
        raise RateLimited(retry_at=when)

    await run_pending(session, max_concurrent=1, chunks_per_file=2, resolver=resolver)

    await session.refresh(item)
    # Sigue siendo trabajo pendiente, no un fallo: marcarlo error obligaría al
    # usuario a reencolarlo a mano cada vez que un hoster gratuito pide esperar.
    assert item.status == "queued"
    assert item.error_message is None
    assert item.retry_after is not None


@pytest.mark.asyncio
async def test_an_item_waiting_is_skipped_until_its_time(session, test_server, tmp_path):
    started = []
    await one_item(
        session, tmp_path, "http://x/a", retry_after=dt.datetime.utcnow() + dt.timedelta(hours=1)
    )

    async def resolver(url, hoster):
        raise AssertionError("no debería haberse levantado")

    await run_pending(
        session, max_concurrent=5, chunks_per_file=2, resolver=resolver,
        _on_start_for_test=started.append,
    )

    assert started == []


@pytest.mark.asyncio
async def test_an_item_whose_wait_expired_is_picked_up(session, test_server, tmp_path):
    payload = b"W" * 100
    _, real_url = await test_server(payload)
    item = await one_item(
        session, tmp_path, "http://x/a", retry_after=dt.datetime.utcnow() - dt.timedelta(minutes=1)
    )

    async def resolver(url, hoster):
        return DirectLink(url=real_url)

    await run_pending(session, max_concurrent=1, chunks_per_file=1, resolver=resolver)

    await session.refresh(item)
    assert item.status == "completed"


@pytest.mark.asyncio
async def test_a_dead_link_fails_the_item_with_its_reason(session, test_server, tmp_path):
    item = await one_item(session, tmp_path, "http://x/gone")

    async def resolver(url, hoster):
        raise LinkDead("el archivo fue borrado")

    await run_pending(session, max_concurrent=1, chunks_per_file=2, resolver=resolver)

    await session.refresh(item)
    assert item.status == "error"
    assert "borrado" in item.error_message


@pytest.mark.asyncio
async def test_resolved_headers_reach_the_request(session, test_server, tmp_path):
    payload = b"H" * 120
    server, real_url = await test_server(payload)
    await one_item(session, tmp_path, "http://x/a")

    async def resolver(url, hoster):
        return DirectLink(url=real_url, headers={"Cookie": "s=1"})

    await run_pending(session, max_concurrent=1, chunks_per_file=1, resolver=resolver)

    assert any(h.get("Cookie") == "s=1" for h in server.seen_headers)
