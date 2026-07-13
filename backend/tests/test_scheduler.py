import warnings

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SAWarning

from app.engine.scheduler import resume_stale_running_items, run_pending
from app.models import Chunk, DownloadItem, Package


@pytest.mark.asyncio
async def test_run_pending_downloads_queued_item_end_to_end(session, test_server, tmp_path):
    payload = b"Z" * 400
    _, url = await test_server(payload, support_range=True)

    package = Package(name="pkg", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    item = DownloadItem(package_id=package.id, url=url, filename="out.bin", status="queued")
    session.add(item)
    await session.commit()

    await run_pending(session, max_concurrent=2, chunks_per_file=4, identity=lambda u: u)

    await session.refresh(item)
    await session.refresh(package)
    assert item.status == "completed"
    assert item.downloaded_bytes == 400
    assert package.status == "completed"
    assert (tmp_path / "out.bin").read_bytes() == payload

    chunks = (await session.execute(select(Chunk).where(Chunk.download_item_id == item.id))).scalars().all()
    assert len(chunks) == 4
    assert all(c.status == "completed" for c in chunks)


@pytest.mark.asyncio
async def test_run_pending_respects_concurrency_limit(session, test_server, tmp_path):
    _, url1 = await test_server(b"A" * 100)
    _, url2 = await test_server(b"B" * 100)
    _, url3 = await test_server(b"C" * 100)

    package = Package(name="pkg", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    for i, url in enumerate([url1, url2, url3]):
        session.add(DownloadItem(package_id=package.id, url=url, filename=f"f{i}.bin", status="queued"))
    await session.commit()

    started: list[str] = []

    await run_pending(
        session,
        max_concurrent=2,
        chunks_per_file=1,
        identity=lambda u: u,
        _on_start_for_test=lambda item_id: started.append(item_id),
    )

    result = await session.execute(select(DownloadItem).where(DownloadItem.package_id == package.id))
    items = result.scalars().all()
    assert sum(1 for i in items if i.status == "completed") == 2
    assert sum(1 for i in items if i.status == "queued") == 1
    assert len(started) == 2  # only max_concurrent items started in this one run_pending() call


@pytest.mark.asyncio
async def test_run_pending_concurrent_items_do_not_corrupt_shared_session(session, test_server, tmp_path):
    """Regression test for a session-corruption race: concurrently-running
    items must never mutate SQLAlchemy-mapped attributes on the shared
    session outside db_lock. If they do, another item's locked commit() can
    autoflush mid-flight and hit the just-dirtied attribute, and SQLAlchemy
    raises "Attribute history events accumulated ... have been reset" as an
    SAWarning - turning that warning into a hard error here makes the race
    deterministically fail the test instead of only showing up as flaky lost
    progress under real concurrency.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=SAWarning)

        package = Package(name="pkg", status="queued", target_dir=str(tmp_path))
        session.add(package)
        await session.flush()
        _, url1 = await test_server(b"A" * 500)
        _, url2 = await test_server(b"B" * 500)
        session.add(DownloadItem(package_id=package.id, url=url1, filename="a.bin", status="queued"))
        session.add(DownloadItem(package_id=package.id, url=url2, filename="b.bin", status="queued"))
        await session.commit()

        # Should not raise SAWarning-turned-error even under real concurrency
        await run_pending(session, max_concurrent=2, chunks_per_file=2, identity=lambda u: u)

    result = await session.execute(select(DownloadItem).where(DownloadItem.package_id == package.id))
    assert all(i.status == "completed" for i in result.scalars().all())


@pytest.mark.asyncio
async def test_resume_stale_running_items_requeues_them(session):
    package = Package(name="pkg", status="running", target_dir="/tmp")
    session.add(package)
    await session.flush()
    item = DownloadItem(package_id=package.id, url="https://example.com/x", filename="x", status="running")
    session.add(item)
    await session.commit()

    await resume_stale_running_items(session)

    await session.refresh(item)
    assert item.status == "queued"
