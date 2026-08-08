import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app


def test_health_endpoint_still_works_with_lifespan():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200


def test_startup_survives_an_unreachable_database(monkeypatch):
    """A DB that is down at boot must not stop the API from serving.

    The resume pass is best-effort recovery, not a startup precondition -
    letting it propagate would make the whole app unbootable whenever
    Postgres happens to come up a few seconds after the app container.
    """

    async def boom(db):
        raise ConnectionRefusedError("postgres is not up yet")

    monkeypatch.setattr(main, "resume_stale_running_items", boom)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


@pytest.mark.asyncio
async def test_scheduler_loop_keeps_polling_after_a_failing_tick(monkeypatch):
    """One bad tick (DB blip, transient engine error) must not kill the loop.

    Without this, a single exception would end the task silently and the
    server would keep serving the API while never starting another download.
    """
    ticks = 0

    async def failing_tick():
        nonlocal ticks
        ticks += 1
        raise RuntimeError("db is down")

    monkeypatch.setattr(main, "_scheduler_tick", failing_tick)
    monkeypatch.setattr(main, "_POLL_INTERVAL_SECONDS", 0.01)

    task = asyncio.create_task(main._scheduler_loop())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ticks >= 2, f"loop stopped after {ticks} tick(s)"


@pytest.mark.asyncio
async def test_scheduler_ticks_are_serialized_not_overlapped(monkeypatch):
    """run_pending's single-flight precondition: never two ticks in flight.

    run_pending creates a fresh lock per call, so two overlapping calls would
    each get their own and defeat the shared-session mutual exclusion.
    """
    in_flight = 0
    max_in_flight = 0

    async def slow_tick():
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1

    monkeypatch.setattr(main, "_scheduler_tick", slow_tick)
    monkeypatch.setattr(main, "_POLL_INTERVAL_SECONDS", 0.001)

    task = asyncio.create_task(main._scheduler_loop())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert max_in_flight == 1
