"""Chunk progress must be persisted while a download runs, not only at the end.

Without this, a process restart mid-download re-fetches every byte: the resume
machinery reads chunk.downloaded_bytes, which stayed 0 for the whole run.
"""

import asyncio

import pytest
from sqlalchemy import select

from app.engine.downloader import download_chunk
from app.engine.item_runner import run_download_item
from app.engine.scheduler import _write_checkpoint, resume_stale_running_items, run_pending
from app.models import Chunk, DownloadItem, Package


@pytest.mark.asyncio
async def test_checkpoint_offsets_are_on_disk_when_reported(test_server, tmp_path):
    payload = bytes(range(256)) * 200  # 51200 bytes, distinctive content
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    # Every reported offset is checked immediately against a separate handle:
    # download_chunk writes through a buffered writer it only closes at the
    # end, so an offset reported before a flush would name bytes that are not
    # actually on disk - and resuming there would leave a hole in the file.
    checkpoints: list[int] = []

    def on_flush(durable_bytes: int) -> None:
        checkpoints.append(durable_bytes)
        assert dest.read_bytes()[:durable_bytes] == payload[:durable_bytes]

    await download_chunk(
        url=url,
        start=0,
        end=len(payload) - 1,
        dest_path=str(dest),
        on_flush=on_flush,
        flush_interval_seconds=0,  # checkpoint on every block, for the test
    )

    assert checkpoints, "no checkpoint was ever reported"
    assert checkpoints[-1] == len(payload)
    assert checkpoints == sorted(checkpoints)


@pytest.mark.asyncio
async def test_checkpoint_offsets_account_for_the_resumed_prefix(test_server, tmp_path):
    payload = b"A" * 200 + b"B" * 300
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(payload[:200] + b"\x00" * 300)

    checkpoints: list[int] = []

    await download_chunk(
        url=url,
        start=0,
        end=499,
        dest_path=str(dest),
        resume_from=200,
        on_flush=checkpoints.append,
        flush_interval_seconds=0,
    )

    # Reported as an absolute offset within the chunk, not bytes-this-attempt:
    # the scheduler stores it straight back as the next resume_from.
    assert checkpoints[-1] == 500


@pytest.mark.asyncio
async def test_item_runner_reports_checkpoints_per_chunk(test_server, tmp_path):
    payload = b"Z" * 4000
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    seen: dict[int, int] = {}

    await run_download_item(
        url=url,
        dest_path=str(dest),
        num_chunks=4,
        on_checkpoint=lambda index, n: seen.__setitem__(index, n),
        flush_interval_seconds=0,
    )

    assert set(seen) == {0, 1, 2, 3}
    assert sum(seen.values()) == 4000


@pytest.mark.asyncio
async def test_write_checkpoint_persists_flushed_offsets(session, tmp_path):
    package = Package(name="pkg", status="running", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    item = DownloadItem(package_id=package.id, url="http://x/f", filename="f", status="running")
    session.add(item)
    await session.flush()
    chunks = [
        Chunk(download_item_id=item.id, range_start=0, range_end=99, status="running"),
        Chunk(download_item_id=item.id, range_start=100, range_end=199, status="running"),
    ]
    session.add_all(chunks)
    await session.commit()

    await _write_checkpoint(session, asyncio.Lock(), {0: 40, 1: 25}, chunks, item)

    reloaded = (
        (await session.execute(select(Chunk).where(Chunk.download_item_id == item.id).order_by(Chunk.range_start)))
        .scalars()
        .all()
    )
    assert [c.downloaded_bytes for c in reloaded] == [40, 25]
    assert item.downloaded_bytes == 65


@pytest.mark.asyncio
async def test_progress_is_committed_while_the_download_is_still_running(
    session, test_server, tmp_path, monkeypatch
):
    """The defect itself: nothing wrote a checkpoint until the item finished.

    Chunk rows were created with flush() and never committed, and their
    downloaded_bytes was only set on completion - so a process that died
    mid-download left nothing behind to resume from, and the resume path
    (which works, and is covered below) always read zeros.
    """
    payload = b"M" * 8000
    # Dripped out over ~80ms so the checkpoint loop below actually gets to tick
    # mid-download instead of racing loopback throughput.
    _, url = await test_server(payload, stream_delay_seconds=0.01)

    package = Package(name="pkg", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    item = DownloadItem(package_id=package.id, url=url, filename="out.bin", status="queued")
    session.add(item)
    await session.commit()

    import app.engine.scheduler as scheduler

    monkeypatch.setattr(scheduler, "CHECKPOINT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(scheduler, "FLUSH_INTERVAL_SECONDS", 0)

    # Records what each checkpoint actually committed, so a partial write is
    # distinguishable from the single final one the old code did.
    committed_sums: list[int] = []
    original = scheduler._write_checkpoint

    async def recording_checkpoint(db, db_lock, checkpoint_by_index, chunks_ref, tracked_item):
        await original(db, db_lock, checkpoint_by_index, chunks_ref, tracked_item)
        if chunks_ref:
            committed_sums.append(sum(checkpoint_by_index.values()))

    monkeypatch.setattr(scheduler, "_write_checkpoint", recording_checkpoint)

    await run_pending(session, max_concurrent=1, chunks_per_file=2, identity=lambda u: u)

    assert committed_sums, "no checkpoint was committed during the download"
    assert any(0 < total < len(payload) for total in committed_sums), (
        f"every checkpoint was all-or-nothing: {committed_sums}"
    )


@pytest.mark.asyncio
async def test_a_restart_resumes_from_the_persisted_checkpoints(session, test_server, tmp_path):
    """The regression test for the defect found in the Fase 1 E2E smoke test.

    Before checkpointing, chunk rows were flushed but never committed and their
    downloaded_bytes stayed 0 for the whole run, so a backend restart re-fetched
    every byte from 0 while still producing a correct file - the waste was
    invisible unless you watched the Range headers.
    """
    payload = bytes(range(256)) * 40  # 10240 bytes
    server, url = await test_server(payload)

    package = Package(name="pkg", status="running", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    item = DownloadItem(
        package_id=package.id, url=url, filename="out.bin", status="running", total_size=len(payload)
    )
    session.add(item)
    await session.flush()

    # Stand in for the state a crashed process left behind: two chunks, each
    # half done, with those bytes already written to disk.
    half = len(payload) // 2
    session.add_all(
        [
            Chunk(download_item_id=item.id, range_start=0, range_end=half - 1,
                  downloaded_bytes=1000, status="running"),
            Chunk(download_item_id=item.id, range_start=half, range_end=len(payload) - 1,
                  downloaded_bytes=2000, status="running"),
        ]
    )
    await session.commit()

    dest = tmp_path / "out.bin"
    dest.write_bytes(payload[:1000] + b"\x00" * (half - 1000) + payload[half : half + 2000]
                     + b"\x00" * (len(payload) - half - 2000))

    await resume_stale_running_items(session)
    await run_pending(session, max_concurrent=1, chunks_per_file=2, identity=lambda u: u)

    await session.refresh(item)
    assert item.status == "completed"
    assert dest.read_bytes() == payload

    # The point: it asked for the missing tails, not the whole file again.
    assert sorted(server.requested_ranges) == [(1000, half - 1), (half + 2000, len(payload) - 1)]
