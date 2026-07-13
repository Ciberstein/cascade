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
