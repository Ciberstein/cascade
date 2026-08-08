import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.packages import router as packages_router
from app.api.settings import router as settings_router
from app.config import Settings
from app.database import SessionLocal
from app.engine.scheduler import resume_stale_running_items, run_pending
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


def _identity(url: str) -> str:
    """Placeholder URL resolver - Fase 2 replaces this with the hoster plugins."""
    return url


async def _effective_limits(db: "AsyncSession") -> tuple[int, int]:
    """(max_concurrent_downloads, chunks_per_file), preferring the settings row.

    Read per tick rather than cached at import: a change saved from the
    Settings page has to take effect without restarting the container.
    """
    row = await read_settings(db)
    if row is None:
        return _settings.max_concurrent_downloads, _settings.chunks_per_file
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
            identity=_identity,
        )


async def _scheduler_loop() -> None:
    while True:
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
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with SessionLocal() as db:
            await resume_stale_running_items(db)
    except Exception:  # noqa: BLE001 - best-effort recovery, not a boot precondition
        # The DB is commonly not accepting connections yet when the app
        # container starts alongside it; failing startup here would make the
        # API unbootable for that window instead of just skipping the resume.
        logger.exception("startup resume of stale running items failed; continuing without it")

    task = asyncio.create_task(_scheduler_loop()) if _settings.scheduler_enabled else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="Cascade", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(packages_router)
app.include_router(settings_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
