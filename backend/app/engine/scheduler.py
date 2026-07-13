import asyncio
import os
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.item_runner import run_download_item
from app.engine.progress import ThrottledBroadcaster
from app.models import Chunk, DownloadItem, Package
from app.ws.manager import manager

_broadcaster = ThrottledBroadcaster(broadcast_fn=manager.broadcast)


async def resume_stale_running_items(db: AsyncSession) -> None:
    """Requeue items left in "running" state by a prior process that crashed/restarted.

    Chunk rows and their downloaded_bytes are left untouched - only the
    positional chunk boundaries are trusted across a restart, not the exact
    in-flight byte offsets (see run_pending's docstring for why).
    """
    result = await db.execute(select(DownloadItem).where(DownloadItem.status == "running"))
    for item in result.scalars().all():
        item.status = "queued"
    await db.commit()


def _dest_path(item: DownloadItem) -> str:
    package_dir = item.package.target_dir if item.package else "/downloads"
    return os.path.join(package_dir, item.filename)


async def _run_one_item(
    db: AsyncSession,
    db_lock: asyncio.Lock,
    item: DownloadItem,
    chunks_per_file: int,
    identity: Callable[[str], str],
) -> None:
    async with db_lock:
        item.status = "running"
        await db.commit()

    resolved_url = identity(item.url)
    dest_path = _dest_path(item)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    async with db_lock:
        existing_result = await db.execute(
            select(Chunk).where(Chunk.download_item_id == item.id).order_by(Chunk.range_start)
        )
        chunks_ref: list[Chunk] = list(existing_result.scalars().all())
    existing_progress = {i: c.downloaded_bytes for i, c in enumerate(chunks_ref)}

    async def on_chunks_planned(ranges: list[tuple[int, int]]) -> None:
        if chunks_ref:
            return  # resuming: rows already exist for this item, reuse them as-is
        async with db_lock:
            for start, end in ranges:
                chunk = Chunk(download_item_id=item.id, range_start=start, range_end=end, status="running")
                db.add(chunk)
                chunks_ref.append(chunk)
            await db.flush()

    # NOTE on this local (non-ORM) counter, deliberately deviating from a
    # literal "just mutate item.downloaded_bytes in on_progress" reading of
    # the task's pseudocode: on_progress is invoked synchronously (no await
    # point available - see item_runner/downloader, on_bytes is a plain sync
    # callback) from inside run_download_item's concurrently-running chunk
    # downloads, so it can never acquire db_lock. But item.downloaded_bytes
    # is a mapped SQLAlchemy attribute, and mutating *any* mapped attribute
    # on an object attached to the shared session dirties that session's
    # unit-of-work state immediately - regardless of whether the mutating
    # code "holds a lock". Reproduced empirically: with item.downloaded_bytes
    # mutated directly here, a concurrently-running item's locked commit()
    # can autoflush mid-flight, walk into this item's freshly-dirtied
    # attribute, and SQLAlchemy raises a hard PendingRollbackError ("Attribute
    # history events accumulated on N previously clean instances within
    # inner-flush event handlers have been reset"), poisoning the whole
    # shared session for every other concurrently-running item too. Keeping
    # per-byte progress in a plain local variable (untracked by the ORM) and
    # only writing it into item.downloaded_bytes inside the lock, atomically
    # with the finalizing commit, avoids ever dirtying the session from
    # unlocked code.
    downloaded_so_far = sum(existing_progress.values())

    def on_progress(chunk_index: int, n: int) -> None:
        nonlocal downloaded_so_far
        downloaded_so_far += n
        _broadcaster.report(item_id=item.id, downloaded_bytes=downloaded_so_far)

    try:
        result = await run_download_item(
            url=resolved_url,
            dest_path=dest_path,
            num_chunks=chunks_per_file,
            existing_progress=existing_progress,
            on_progress=on_progress,
            on_chunks_planned=on_chunks_planned,
        )
        # Mutating item/chunk attributes must happen inside the lock, atomically
        # with the commit that follows: mutating them first and committing in a
        # separate locked section (as a naive reading of "only wrap DB calls"
        # would suggest) leaves a window where another concurrently-running
        # item's locked db.execute() can trigger SQLAlchemy's autoflush, which
        # walks the *whole* session's dirty set - including these not-yet-locked
        # mutations - and silently discards them ("attribute history reset")
        # if they're touched again before this task reaches its own commit.
        async with db_lock:
            item.total_size = result.total_size
            item.downloaded_bytes = result.total_size
            item.status = "completed"
            for chunk in chunks_ref:
                chunk.status = "completed"
                chunk.downloaded_bytes = chunk.range_end - chunk.range_start + 1
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - persist failure state, don't crash run_pending
        async with db_lock:
            item.status = "error"
            item.error_message = str(exc)
            item.downloaded_bytes = downloaded_so_far
            await db.commit()


async def run_pending(
    db: AsyncSession,
    max_concurrent: int,
    chunks_per_file: int,
    identity: Callable[[str], str],
    _on_start_for_test: Callable[[str], None] | None = None,
) -> None:
    """Pick up to `max_concurrent` queued items and download them concurrently.

    Intended to be invoked repeatedly on a loop by the app lifespan - this
    function itself does not keep polling for more work once it has picked
    its batch; a follow-up call is what picks up anything left over.

    All DB access here shares the single `db` session passed in, so every
    touchpoint (including the one inside on_chunks_planned, which fires from
    inside the concurrently-running run_download_item calls) is serialized
    via `db_lock`. Only network I/O and pure in-memory attribute mutation
    run unsynchronized.
    """
    db_lock = asyncio.Lock()

    result = await db.execute(
        select(DownloadItem).where(DownloadItem.status == "queued").limit(max_concurrent)
    )
    items = result.scalars().all()

    for item in items:
        await db.refresh(item, attribute_names=["package"])
        if _on_start_for_test:
            _on_start_for_test(item.id)

    await asyncio.gather(*(_run_one_item(db, db_lock, item, chunks_per_file, identity) for item in items))

    package_ids = {item.package_id for item in items}
    for package_id in package_ids:
        pkg_result = await db.execute(select(Package).where(Package.id == package_id))
        package = pkg_result.scalar_one()
        items_result = await db.execute(select(DownloadItem).where(DownloadItem.package_id == package_id))
        pkg_items = items_result.scalars().all()
        if pkg_items and all(i.status == "completed" for i in pkg_items):
            package.status = "completed"
    await db.commit()
