import asyncio
import time

import pytest

from app.engine.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_unlimited_never_waits():
    rl = RateLimiter(0)
    start = time.monotonic()

    for _ in range(200):
        await rl.acquire(1_000_000)

    assert time.monotonic() - start < 0.2


@pytest.mark.asyncio
async def test_throughput_is_capped():
    rl = RateLimiter(10_000)  # 10 KB/s
    start = time.monotonic()

    # 5000 bytes at 10 KB/s: the bucket starts empty, so this needs ~0.5s.
    for _ in range(5):
        await rl.acquire(1000)

    elapsed = time.monotonic() - start
    assert 0.35 <= elapsed <= 1.2, elapsed


@pytest.mark.asyncio
async def test_the_cap_is_shared_across_concurrent_callers():
    rl = RateLimiter(10_000)
    start = time.monotonic()

    # 4 chunks pulling 1000 bytes each: a per-caller limiter would finish these
    # in the time one caller takes, defeating a "global" speed limit.
    await asyncio.gather(*(rl.acquire(1000) for _ in range(4)))

    elapsed = time.monotonic() - start
    assert elapsed >= 0.25, elapsed


@pytest.mark.asyncio
async def test_lifting_the_cap_takes_effect_immediately():
    rl = RateLimiter(1)  # 1 B/s - a 1000-byte acquire would take ~1000s
    task = asyncio.create_task(rl.acquire(1000))
    await asyncio.sleep(0.05)

    rl.set_rate(0)

    # Saving "0 = sin límite" must release downloads already blocked on the
    # old cap, not leave them parked until the old debt is paid off.
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_a_block_larger_than_one_second_of_credit_still_completes():
    rl = RateLimiter(10_000)  # 10 KB/s
    start = time.monotonic()

    # httpx yields blocks of tens of KB, so this is the ordinary case for any
    # modest cap - not an edge case. A bucket whose ceiling is one second of
    # tokens can never satisfy it and hangs the download forever.
    await asyncio.wait_for(rl.acquire(30_000), timeout=10.0)

    elapsed = time.monotonic() - start
    assert elapsed >= 2.0, elapsed


@pytest.mark.asyncio
async def test_idle_time_does_not_bank_unlimited_credit():
    rl = RateLimiter(10_000)
    await asyncio.sleep(0.4)  # idle: an uncapped bucket would hold 4000 tokens

    start = time.monotonic()
    await rl.acquire(10_000)
    elapsed = time.monotonic() - start

    # Credit is capped at one second's worth, so ~0.6s of it is forfeited
    # rather than carried forward into a burst that ignores the limit.
    assert elapsed >= 0.5, elapsed
