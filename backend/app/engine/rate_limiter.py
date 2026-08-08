"""Global download speed cap (the `max_speed_kbps` setting)."""

import asyncio
import time

#: Upper bound on a single sleep inside acquire, so a rate change is picked up
#: promptly instead of after a wait sized by the rate that was in force before.
_MAX_SLEEP_SLICE_SECONDS = 0.25


class RateLimiter:
    """Token bucket shared by every in-flight chunk.

    The cap is global, not per-chunk: with 4 chunks running, each one waiting
    on its own private limiter would let the process use 4x the configured
    speed. One shared bucket is what makes the number in Settings mean what it
    says.

    `acquire` holds the lock across its sleep so waiters are served roughly in
    arrival order rather than the fastest connection starving the others.
    """

    def __init__(self, rate_bytes_per_second: float = 0) -> None:
        self._rate = rate_bytes_per_second
        self._tokens = 0.0
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def rate_bytes_per_second(self) -> float:
        return self._rate

    def set_rate(self, rate_bytes_per_second: float) -> None:
        """Change the cap mid-download; 0 (or less) means unlimited.

        Resets the bucket so a long unlimited stretch can't bank credit and
        then blow straight through a newly-applied limit.
        """
        self._rate = max(0.0, rate_bytes_per_second)
        self._tokens = 0.0
        self._updated = time.monotonic()

    async def acquire(self, byte_count: int) -> None:
        """Wait until `byte_count` bytes may be counted against the cap."""
        if self._rate <= 0:
            return  # unlimited - stay entirely out of the way, no lock, no sleep

        async with self._lock:
            while True:
                rate = self._rate
                if rate <= 0:
                    return  # the cap was lifted while we waited

                # Capacity is at least this request's size. A fixed ceiling of
                # one second's worth would deadlock outright whenever a single
                # read is bigger than that - httpx hands over blocks of tens of
                # KB, so any cap below ~64 KB/s would hang the download forever
                # waiting for tokens that can never accumulate.
                capacity = max(rate, byte_count)

                now = time.monotonic()
                self._tokens = min(capacity, self._tokens + (now - self._updated) * rate)
                self._updated = now

                if self._tokens >= byte_count:
                    self._tokens -= byte_count
                    return

                # Sliced rather than slept off in one go so a cap raised or
                # lifted from the Settings page is noticed within a tick,
                # instead of after a wait computed from the old rate.
                wait = (byte_count - self._tokens) / rate
                await asyncio.sleep(min(wait, _MAX_SLEEP_SLICE_SECONDS))


#: Shared by every download in the process; the scheduler keeps its rate in
#: sync with the settings row.
limiter = RateLimiter()
