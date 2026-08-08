import asyncio
import time
from typing import Awaitable, Callable


class ThrottledBroadcaster:
    def __init__(self, broadcast_fn: Callable[[dict], Awaitable[None]], interval_seconds: float = 0.5):
        self._broadcast_fn = broadcast_fn
        self._interval = interval_seconds
        self._latest: dict[str, dict] = {}
        self._last_sent: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def report(self, item_id: str, downloaded_bytes: int) -> None:
        self._latest[item_id] = {"type": "progress", "item_id": item_id, "downloaded_bytes": downloaded_bytes}
        asyncio.create_task(self._maybe_send(item_id))

    async def _maybe_send(self, item_id: str) -> None:
        now = time.monotonic()
        last = self._last_sent.get(item_id, 0)
        if now - last < self._interval:
            return
        async with self._lock:
            payload = self._latest.get(item_id)
            if payload is None:
                return
            self._last_sent[item_id] = now
            await self._broadcast_fn(payload)

    async def flush(self) -> None:
        async with self._lock:
            for item_id, payload in list(self._latest.items()):
                await self._broadcast_fn(payload)
                self._last_sent[item_id] = time.monotonic()
