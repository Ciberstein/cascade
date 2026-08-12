import asyncio

import pytest

from app import main
from app.models import GlobalSettings
from app.plugins.base import DirectLink


@pytest.mark.asyncio
async def test_the_resolver_uses_the_plugin_named_on_the_item():
    link = await main._resolve("https://pixeldrain.com/u/abc123", "pixeldrain")
    assert link.url == "https://pixeldrain.com/api/file/abc123?download"


@pytest.mark.asyncio
async def test_an_unknown_hoster_falls_back_to_matching_by_url():
    # Un plugin puede desaparecer entre que se encoló el item y que se levantó
    # (renombre, borrado). Fallar el item por eso sería peor que reintentar el
    # matching, que en el peor caso cae en direct.
    link = await main._resolve("http://example.com/a.zip", "un-plugin-que-ya-no-existe")
    assert link.url == "http://example.com/a.zip"


@pytest.mark.asyncio
async def test_the_crawl_loop_survives_a_failing_tick(monkeypatch):
    ticks = 0

    async def failing_tick():
        nonlocal ticks
        ticks += 1
        raise RuntimeError("db caída")

    monkeypatch.setattr(main, "_crawl_tick", failing_tick)
    monkeypatch.setattr(main, "_CRAWL_POLL_INTERVAL_SECONDS", 0.01)

    task = asyncio.create_task(main._crawl_loop())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ticks >= 2


@pytest.mark.asyncio
async def test_crawl_concurrency_follows_the_settings_row(session):
    session.add(GlobalSettings(id=1, max_concurrent_crawls=9))
    await session.commit()

    assert await main._effective_crawl_limit(session) == 9


@pytest.mark.asyncio
async def test_crawl_concurrency_falls_back_on_a_fresh_install(session):
    assert await main._effective_crawl_limit(session) == 5


@pytest.mark.asyncio
async def test_setting_the_stop_flag_ends_both_loops_promptly(monkeypatch):
    """Apagar no debe esperar a que venza el intervalo de sondeo.

    Regresión: con el flag como global de módulo, cada loop lo reemplazaba al
    arrancar, así que el segundo en iniciar dejaba al primero esperando un
    Event que nadie iba a levantar - y ese primero solo se enteraba del apagado
    cuando su propio timeout vencía.
    """

    async def noop():
        return None

    monkeypatch.setattr(main, "_scheduler_tick", noop)
    monkeypatch.setattr(main, "_crawl_tick", noop)
    monkeypatch.setattr(main, "_POLL_INTERVAL_SECONDS", 30)
    monkeypatch.setattr(main, "_CRAWL_POLL_INTERVAL_SECONDS", 30)

    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(main._scheduler_loop(stop)),
        asyncio.create_task(main._crawl_loop(stop)),
    ]
    await asyncio.sleep(0.05)
    stop.set()

    # Con intervalos de 30s, cualquier loop que no despierte con el flag
    # agotaría este wait_for.
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=2.0)


@pytest.mark.asyncio
async def test_each_loop_gets_its_own_flag_when_none_is_passed():
    """Sin esto, un Event de módulo quedaría atado al event loop del primer
    test que lo esperara y el siguiente fallaría con "bound to a different
    event loop"."""
    task = asyncio.create_task(main._crawl_loop())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
