import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.api.account import router as account_router
from app.api.crawl_jobs import router as crawl_jobs_router
from app.api.packages import router as packages_router
from app.api.settings import router as settings_router
from app.config import Settings
from app.crawler.runner import requeue_stale_running_jobs, run_pending_crawls
from app.database import SessionLocal
from app.engine.rate_limiter import limiter
from app.engine.scheduler import (
    reconcile_package_statuses,
    resume_stale_running_items,
    run_pending,
)
from app.plugins.base import DirectLink, PluginError, UnsupportedLink
from app.retention import sweep
from app.plugins.registry import call_resolve, registry
from app.settings_store import read_settings
from app.ws.routes import router as ws_router

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_settings = Settings()

# How long to wait between polls for newly queued items. Also the pause after
# a failed tick, so a persistently unreachable DB retries at a steady rate
# instead of spinning.
_POLL_INTERVAL_SECONDS = 2.0

#: Crawls are short and the user is watching the tray, so this polls more
#: often than downloads do.
_CRAWL_POLL_INTERVAL_SECONDS = 1.0

#: The sweep is in no hurry: what it frees has already served its purpose.
#: Running it often would only burn queries.
_SWEEP_INTERVAL_SECONDS = 300.0


async def _resolve(url: str, hoster: str, format_id: str | None = None) -> DirectLink:
    """Returns the direct URL using the plugin the item was queued with.

    If that plugin no longer exists (renamed or removed between queueing and
    startup), it re-matches by URL instead of failing the item: at worst it
    falls back to `direct`, which is exactly what Phase 1 did.
    """
    named = registry.get(hoster)
    candidates = [named] if named is not None else []
    # The rest stay behind as alternatives: if the plugin it was queued with
    # answers UnsupportedLink (the URL changed shape, the site stopped serving
    # what it served), we keep trying down to `direct` instead of failing the
    # item.
    candidates += [p for p in registry.candidates(url) if p is not named]

    last: UnsupportedLink | None = None
    for plugin in candidates:
        try:
            return await call_resolve(plugin, url, format_id)
        except UnsupportedLink as exc:
            last = exc
            continue
    raise last if last is not None else PluginError(f"no plugin resolved {url}")


async def _effective_limits(db: "AsyncSession") -> tuple[int, int]:
    """(max_concurrent_downloads, chunks_per_file), preferring the settings row.

    Read per tick rather than cached at import: a change saved from the
    Settings page has to take effect without restarting the container. Also
    syncs the shared speed limiter for the same reason - the limiter reads its
    rate on every acquire, so a change lands on downloads already in flight.
    """
    row = await read_settings(db)
    if row is None:
        limiter.set_rate(0)  # fresh install: no row yet, so no cap
        return _settings.max_concurrent_downloads, _settings.chunks_per_file

    if limiter.rate_bytes_per_second != row.max_speed_kbps * 1024:
        limiter.set_rate(row.max_speed_kbps * 1024)
    return row.max_concurrent_downloads, row.chunks_per_file


async def _scheduler_tick() -> None:
    """One polling pass: pick up queued items and download them to completion.

    Each tick gets its own session, so a session poisoned by a failed tick is
    discarded rather than carried into the next one.
    """
    async with SessionLocal() as db:
        max_concurrent, chunks_per_file = await _effective_limits(db)
        await run_pending(
            db,
            max_concurrent=max_concurrent,
            chunks_per_file=chunks_per_file,
            resolver=_resolve,
        )


async def _scheduler_loop(stop: asyncio.Event | None = None) -> None:
    """Runs ticks until `stop` is raised.

    The Event arrives as a parameter rather than living as a module global: an
    `asyncio.Event` binds to the first event loop that awaits it, and every
    pytest-asyncio test runs in its own, so a singleton would raise "bound to a
    different event loop" on the second test to use it - besides inheriting the
    set() the previous lifespan left behind on shutdown. Callers who pass
    nothing (the tests) get their own.
    """
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            # Awaited to completion before the next iteration starts: run_pending
            # documents a single-flight precondition (it builds a fresh db_lock
            # per call, so two overlapping calls would each get their own and
            # silently defeat the shared-session mutual exclusion it relies on).
            await _scheduler_tick()
        except Exception:  # noqa: BLE001 - a bad tick must not kill the loop
            # CancelledError is a BaseException, so shutdown still propagates
            # out of here and ends the task as intended.
            logger.exception("scheduler tick failed; retrying after the poll interval")
        with suppress(TimeoutError):
            # wait_for on the flag rather than sleep: shutdown doesn't wait a
            # whole interval, and waking early is safe because the while check
            # happens before the next tick.
            await asyncio.wait_for(stop.wait(), timeout=_POLL_INTERVAL_SECONDS)


async def _effective_crawl_limit(db: "AsyncSession") -> int:
    row = await read_settings(db)
    if row is None:
        return _settings.max_concurrent_crawls
    return row.max_concurrent_crawls


async def _crawl_tick() -> None:
    async with SessionLocal() as db:
        await run_pending_crawls(db, max_concurrent=await _effective_crawl_limit(db))


async def _crawl_loop(stop: asyncio.Event | None = None) -> None:
    """Same contract as _scheduler_loop; see there why the Event isn't global."""
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            # Awaited to completion before the next cycle: run_pending_crawls
            # shares the same single-flight precondition as run_pending.
            await _crawl_tick()
        except Exception:  # noqa: BLE001 - un tick malo no puede matar el loop
            logger.exception("crawl tick failed; retrying after the poll interval")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=_CRAWL_POLL_INTERVAL_SECONDS)


async def _sweep_tick() -> None:
    async with SessionLocal() as db:
        freed = await sweep(
            db,
            grace_minutes=_settings.retrieval_grace_minutes,
            max_retention_hours=_settings.max_retention_hours,
        )
    if freed:
        logger.info("liberados %s archivos del servidor", freed)


async def _sweep_loop(stop: asyncio.Event | None = None) -> None:
    """Mismo contrato que los otros loops; ver _scheduler_loop."""
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            await _sweep_tick()
        except Exception:  # noqa: BLE001 - un barrido fallido no puede matar el loop
            logger.exception("sweep tick failed; retrying after the interval")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=_SWEEP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with SessionLocal() as db:
            await resume_stale_running_items(db)
            await requeue_stale_running_jobs(db)
            await reconcile_package_statuses(db)
    except Exception:  # noqa: BLE001 - best-effort recovery, not a boot precondition
        # The DB is commonly not accepting connections yet when the app
        # container starts alongside it; failing startup here would make the
        # API unbootable for that window instead of just skipping the resume.
        logger.exception("startup resume of stale running items failed; continuing without it")

    # Uno solo, compartido por ambos loops, para que apagar los despierte a los
    # dos a la vez en lugar de que el segundo espere a que venza su intervalo.
    stop = asyncio.Event()
    tasks = []
    if _settings.scheduler_enabled:
        tasks.append(asyncio.create_task(_scheduler_loop(stop)))
        tasks.append(asyncio.create_task(_crawl_loop(stop)))
        tasks.append(asyncio.create_task(_sweep_loop(stop)))
    try:
        yield
    finally:
        # Orderly shutdown through a flag, not task.cancel(): the crawl runner
        # commits, and a cancellation can land inside the commit and leave the
        # connection half-done, which is exactly what poisoned the shared
        # session in Phase 1. The flag is only observed between ticks.
        stop.set()
        for task in tasks:
            await task


app = FastAPI(title="Cascade", lifespan=lifespan)
app.include_router(account_router)
app.include_router(crawl_jobs_router)
app.include_router(packages_router)
app.include_router(settings_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
