import asyncio
import logging
import os
from contextlib import suppress
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.downloader import FLUSH_INTERVAL_SECONDS
from app.engine.item_runner import run_download_item
from app.engine.progress import ThrottledBroadcaster
from app.engine.rate_limiter import limiter
from app.models import Chunk, DownloadItem, Package
from app.ws.manager import manager

logger = logging.getLogger(__name__)

_broadcaster = ThrottledBroadcaster(broadcast_fn=manager.broadcast)

#: How often flushed chunk offsets are written to the DB while a download runs.
#: A crash loses at most this much progress; the bytes themselves stay on disk.
CHECKPOINT_INTERVAL_SECONDS = 3.0


async def resume_stale_running_items(db: AsyncSession) -> None:
    """Requeue items left in "running" state by a prior process that crashed/restarted.

    Chunk rows and their downloaded_bytes are left untouched on purpose: they
    are the resume point. Each one records an offset that was flushed to disk
    before it was committed (see download_chunk's on_flush), so re-fetching
    from there is safe, and re-fetching from 0 would be pure waste.
    """
    result = await db.execute(select(DownloadItem).where(DownloadItem.status == "running"))
    for item in result.scalars().all():
        item.status = "queued"
    await db.commit()


def _dest_path(item: DownloadItem) -> str:
    package_dir = item.package.target_dir if item.package else "/downloads"
    return os.path.join(package_dir, item.filename)


async def _write_checkpoint(
    db: AsyncSession,
    db_lock: asyncio.Lock,
    checkpoint_by_index: dict[int, int],
    chunks_ref: list[Chunk],
    item: DownloadItem,
) -> None:
    """Persist the flushed per-chunk offsets so a restart can resume from them.

    Chunk indices are positional and line up with chunks_ref, which is ordered
    by range_start - the same order split_into_chunks produced the ranges in.
    """
    if not chunks_ref:
        return  # chunks aren't planned yet; nothing to record
    async with db_lock:
        for index, chunk in enumerate(chunks_ref):
            chunk.downloaded_bytes = checkpoint_by_index.get(index, 0)
        item.downloaded_bytes = sum(checkpoint_by_index.values())
        await db.commit()


async def _checkpoint_loop(
    db: AsyncSession,
    db_lock: asyncio.Lock,
    checkpoint_by_index: dict[int, int],
    chunks_ref: list[Chunk],
    item: DownloadItem,
    stop: asyncio.Event,
) -> None:
    """Writes a checkpoint every CHECKPOINT_INTERVAL_SECONDS until `stop` is set.

    Stopping is a flag rather than task.cancel() on purpose. Cancellation would
    land wherever the task happens to be - including inside db.commit(), which
    leaves the DBAPI connection half-through a transaction. SQLAlchemy then
    invalidates it, and every later statement on the shared session fails. The
    flag is only ever observed between checkpoints, so a commit always runs to
    completion.
    """
    while not stop.is_set():
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=CHECKPOINT_INTERVAL_SECONDS)
        if stop.is_set():
            return
        try:
            await _write_checkpoint(db, db_lock, checkpoint_by_index, chunks_ref, item)
        except Exception:  # noqa: BLE001 - a failed checkpoint must not abort the download
            # Losing a checkpoint costs re-downloaded bytes on the next
            # restart; killing the item over it would cost all of them.
            logger.exception("checkpoint failed for item %s", item.id)


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

    # chunks_ref/downloaded_so_far are declared before the try so the except
    # block can always reference them, even if the setup phase below (URL
    # resolution, directory creation, the resume-chunk lookup) is what threw -
    # see the try's docstring-style comment for why the try starts here and
    # not just around run_download_item.
    chunks_ref: list[Chunk] = []
    downloaded_so_far = 0
    checkpoint_by_index: dict[int, int] = {}

    try:
        # Everything from here through the success commit must stay inside
        # this try: identity() (a future hoster-plugin URL resolver),
        # os.makedirs (PermissionError/OSError on a bad filename), and the
        # locked chunk-lookup db.execute() can all raise. If any of them
        # escaped uncaught, it would propagate through this item's Task,
        # through asyncio.gather (called without return_exceptions=True) in
        # run_pending, and abort every other concurrently-running item's
        # download and package-completion check too - not just this one
        # item's. Catching broadly here keeps a single item's failure
        # contained to that item.
        resolved_url = identity(item.url)
        dest_path = _dest_path(item)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        async with db_lock:
            existing_result = await db.execute(
                select(Chunk).where(Chunk.download_item_id == item.id).order_by(Chunk.range_start)
            )
            chunks_ref.extend(existing_result.scalars().all())
        existing_progress = {i: c.downloaded_bytes for i, c in enumerate(chunks_ref)}
        downloaded_so_far = sum(existing_progress.values())

        async def on_chunks_planned(ranges: list[tuple[int, int]]) -> None:
            if chunks_ref:
                return  # resuming: rows already exist for this item, reuse them as-is
            async with db_lock:
                for start, end in ranges:
                    chunk = Chunk(download_item_id=item.id, range_start=start, range_end=end, status="running")
                    db.add(chunk)
                    chunks_ref.append(chunk)
                # Committed, not just flushed: an uncommitted row vanishes when
                # the process dies, and then the restart has no chunk rows to
                # resume from and re-downloads the item from byte 0.
                await db.commit()

        # NOTE on this local (non-ORM) counter, deliberately deviating from a
        # literal "just mutate item.downloaded_bytes in on_progress" reading
        # of the task's pseudocode: on_progress is invoked synchronously (no
        # await point available - see item_runner/downloader, on_bytes is a
        # plain sync callback) from inside run_download_item's concurrently-
        # running chunk downloads, so it can never acquire db_lock. But
        # item.downloaded_bytes is a mapped SQLAlchemy attribute, and
        # mutating *any* mapped attribute on an object attached to the
        # shared session dirties that session's unit-of-work state
        # immediately - regardless of whether the mutating code "holds a
        # lock". Reproduced empirically: with item.downloaded_bytes mutated
        # directly here, a concurrently-running item's locked commit() can
        # autoflush mid-flight, walk into this item's freshly-dirtied
        # attribute, and SQLAlchemy raises a hard PendingRollbackError
        # ("Attribute history events accumulated on N previously clean
        # instances within inner-flush event handlers have been reset"),
        # poisoning the whole shared session for every other concurrently-
        # running item too. Keeping per-byte progress in a plain local
        # variable (untracked by the ORM) and only writing it into
        # item.downloaded_bytes inside the lock, atomically with the
        # finalizing commit, avoids ever dirtying the session from unlocked
        # code.
        def on_progress(chunk_index: int, n: int) -> None:
            nonlocal downloaded_so_far
            downloaded_so_far += n
            _broadcaster.report(item_id=item.id, downloaded_bytes=downloaded_so_far)

        # Durable per-chunk offsets, kept in a plain dict for exactly the same
        # reason as downloaded_so_far above: on_checkpoint is a sync callback
        # fired from inside the concurrent chunk downloads, so it can never
        # take db_lock, and writing to a mapped attribute from there would
        # dirty the shared session outside the lock. _checkpoint_loop is what
        # moves these into the ORM, under the lock.
        checkpoint_by_index.update(existing_progress)

        def on_checkpoint(chunk_index: int, durable_bytes: int) -> None:
            # max() guards a retry: a failed attempt restarts its byte count
            # from resume_from, and the bytes in between were already flushed
            # (and will be rewritten identically), so the offset must not
            # travel backwards.
            checkpoint_by_index[chunk_index] = max(
                checkpoint_by_index.get(chunk_index, 0), durable_bytes
            )

        stop_checkpointing = asyncio.Event()
        checkpointer = asyncio.create_task(
            _checkpoint_loop(db, db_lock, checkpoint_by_index, chunks_ref, item, stop_checkpointing)
        )
        try:
            result = await run_download_item(
                url=resolved_url,
                dest_path=dest_path,
                num_chunks=chunks_per_file,
                existing_progress=existing_progress,
                on_progress=on_progress,
                on_chunks_planned=on_chunks_planned,
                on_checkpoint=on_checkpoint,
                flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
                # The one process-wide limiter, so the configured speed is a
                # total across every concurrent chunk of every running item.
                rate_limiter=limiter,
            )
        finally:
            # Stopped before the finalizing commit below so it can't interleave
            # a stale checkpoint on top of the completed state. Awaited (not
            # cancelled) so any commit already in flight finishes cleanly - see
            # _checkpoint_loop. Safe from deadlock: db_lock is not held here.
            stop_checkpointing.set()
            await checkpointer
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
            item.downloaded_bytes = downloaded_so_far
            item.status = "completed"
            for chunk in chunks_ref:
                chunk.status = "completed"
                chunk.downloaded_bytes = chunk.range_end - chunk.range_start + 1
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - persist failure state, don't crash run_pending
        async with db_lock:
            # Roll back first: if we got here because the success-path
            # commit above itself failed partway, the session may be in a
            # state where issuing more work without rolling back first would
            # raise again (e.g. PendingRollbackError), breaking this recovery
            # commit too.
            await db.rollback()
            item.status = "error"
            item.error_message = str(exc)
            # Keep the durable offsets rather than the optimistic byte counter:
            # a user who retries this item should pick up from what is actually
            # on disk instead of re-fetching it. The rollback above discarded
            # any uncommitted checkpoint, so re-apply it here.
            for index, chunk in enumerate(chunks_ref):
                chunk.status = "error"
                chunk.downloaded_bytes = checkpoint_by_index.get(index, 0)
            item.downloaded_bytes = (
                sum(checkpoint_by_index.values()) if chunks_ref else downloaded_so_far
            )
            await db.commit()

    # Guarantee the final progress update (e.g. reaching 100%) isn't silently
    # dropped by ThrottledBroadcaster's interval coalescing - report() only
    # sends if interval_seconds has elapsed since the last send for this
    # item_id, so a completion landing within that window would otherwise
    # never reach WS clients. flush() has its own internal lock (Task 17) and
    # is safe/idempotent to call here even though it flushes every item's
    # pending state, not just this one's.
    await _broadcaster.flush()


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

    IMPORTANT - single-flight precondition: callers MUST `await` this
    function to completion before calling it again against the same db
    session/engine - do not call it concurrently or as a fire-and-forget
    background task. `db_lock` is a fresh `asyncio.Lock()` created per call
    and only serializes DB access *within that one call*; two overlapping
    `run_pending()` calls would each get their own independent lock, which
    would silently defeat the mutual-exclusion this function relies on and
    reintroduce the shared-session corruption race this locking design
    exists to prevent (see the on_progress comment in `_run_one_item`).
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
