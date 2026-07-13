import asyncio

import pytest

from app.engine.progress import ThrottledBroadcaster


@pytest.mark.asyncio
async def test_throttled_broadcaster_coalesces_rapid_updates():
    sent: list[dict] = []

    async def fake_broadcast(data: dict) -> None:
        sent.append(data)

    broadcaster = ThrottledBroadcaster(broadcast_fn=fake_broadcast, interval_seconds=0.05)

    for i in range(20):
        broadcaster.report(item_id="item-1", downloaded_bytes=i)

    await asyncio.sleep(0.1)
    await broadcaster.flush()

    assert len(sent) >= 1
    assert sent[-1]["item_id"] == "item-1"
    assert sent[-1]["downloaded_bytes"] == 19


@pytest.mark.asyncio
async def test_flush_does_not_race_with_in_flight_maybe_send():
    concurrent = 0
    max_concurrent = 0
    calls = 0

    async def fake_broadcast(data: dict) -> None:
        nonlocal concurrent, max_concurrent, calls
        calls += 1
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        try:
            await asyncio.sleep(0.05)
        finally:
            concurrent -= 1

    # Long interval so only the first report() triggers a broadcast attempt,
    # keeping the scenario deterministic.
    broadcaster = ThrottledBroadcaster(broadcast_fn=fake_broadcast, interval_seconds=0.5)

    broadcaster.report(item_id="item-1", downloaded_bytes=1)
    # Let the scheduled _maybe_send task start and enter fake_broadcast so it
    # is suspended mid-await (still holding the lock) when flush() runs.
    await asyncio.sleep(0.01)

    await broadcaster.flush()

    assert calls == 2
    assert max_concurrent == 1
