import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.crawl_jobs import router as crawl_jobs_router
from app.api.packages import router as packages_router
from app.api.settings import router as settings_router
from app.config import Settings
from app.crawler.runner import run_pending_crawls
from app.database import SessionLocal
from app.engine.rate_limiter import limiter
from app.engine.scheduler import resume_stale_running_items, run_pending
from app.plugins.base import DirectLink
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

#: Los crawls son cortos y el usuario está mirando la bandeja, así que se
#: sondea más seguido que las descargas.
_CRAWL_POLL_INTERVAL_SECONDS = 1.0

#: Se levanta al apagar. Los loops lo miran entre ticks, nunca a mitad de uno.
_stop_loops = asyncio.Event()


async def _resolve(url: str, hoster: str) -> DirectLink:
    """Devuelve la URL directa usando el plugin con el que se encoló el item.

    Si ese plugin ya no existe (renombrado o eliminado entre que se encoló y
    que se levantó), se vuelve a matchear por URL en vez de fallar el item:
    en el peor caso cae en `direct`, que es exactamente lo que hacía Fase 1.
    """
    plugin = registry.get(hoster) or registry.find(url)
    return await call_resolve(plugin, url)


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


async def _scheduler_loop() -> None:
    # Se reemplaza por un Event nuevo al arrancar, no solo .clear(): el
    # flag es un singleton de módulo y un `asyncio.Event` queda atado al
    # primer event loop que lo espera. Un lifespan previo (o un test) puede
    # haberlo dejado en set() al apagarse, y además cada test de pytest-
    # asyncio corre en su propio event loop - reusar el mismo objeto
    # lanzaría "bound to a different event loop" en el segundo test que
    # lo espera. Un Event nuevo evita ambos problemas.
    global _stop_loops
    _stop_loops = asyncio.Event()
    while not _stop_loops.is_set():
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
            # wait_for sobre el flag en vez de sleep: apagar no espera un
            # intervalo entero, y despertar temprano es seguro porque el chequeo
            # del while ocurre antes del próximo tick.
            await asyncio.wait_for(_stop_loops.wait(), timeout=_POLL_INTERVAL_SECONDS)


async def _effective_crawl_limit(db: "AsyncSession") -> int:
    row = await read_settings(db)
    if row is None:
        return _settings.max_concurrent_crawls
    return row.max_concurrent_crawls


async def _crawl_tick() -> None:
    async with SessionLocal() as db:
        await run_pending_crawls(db, max_concurrent=await _effective_crawl_limit(db))


async def _crawl_loop() -> None:
    # Mismo motivo que en _scheduler_loop: un Event nuevo al arrancar evita
    # heredar tanto un flag ya levantado como un event loop ajeno.
    global _stop_loops
    _stop_loops = asyncio.Event()
    while not _stop_loops.is_set():
        try:
            # Awaited hasta el final antes del siguiente ciclo: run_pending_crawls
            # comparte la misma precondición single-flight que run_pending.
            await _crawl_tick()
        except Exception:  # noqa: BLE001 - un tick malo no puede matar el loop
            logger.exception("crawl tick failed; retrying after the poll interval")
        with suppress(TimeoutError):
            await asyncio.wait_for(_stop_loops.wait(), timeout=_CRAWL_POLL_INTERVAL_SECONDS)


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

    tasks = []
    if _settings.scheduler_enabled:
        tasks.append(asyncio.create_task(_scheduler_loop()))
        tasks.append(asyncio.create_task(_crawl_loop()))
    try:
        yield
    finally:
        # Parada ordenada por flag, no task.cancel(): el runner de crawl commitea,
        # y una cancelación puede caer dentro del commit y dejar la conexión a
        # medias, que es exactamente lo que envenenó la sesión compartida en
        # Fase 1. El flag solo se observa entre ticks.
        _stop_loops.set()
        for task in tasks:
            await task


app = FastAPI(title="Cascade", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(crawl_jobs_router)
app.include_router(packages_router)
app.include_router(settings_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
