import asyncio
from collections.abc import Callable

import httpx


async def download_chunk(
    url: str,
    start: int,
    end: int,
    dest_path: str,
    max_retries: int = 3,
    backoff_base: float = 0.5,
    resume_from: int = 0,
    on_bytes: Callable[[int], None] | None = None,
) -> None:
    range_start = start + resume_from
    expected_bytes = end - range_start + 1

    if expected_bytes <= 0:
        # resume_from already covers the whole chunk (e.g. a prior attempt
        # finished this chunk but the overall item wasn't marked complete) -
        # nothing left to fetch, and start > end would make for an invalid
        # Range header anyway.
        return

    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Range": f"bytes={range_start}-{end}"}
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code not in (200, 206):
                        raise RuntimeError(f"Unexpected status {response.status_code}")

                    written = 0
                    with open(dest_path, "r+b") as f:
                        f.seek(range_start)
                        async for data in response.aiter_bytes():
                            f.write(data)
                            written += len(data)
                            if on_bytes is not None:
                                on_bytes(len(data))

                    if written != expected_bytes:
                        raise RuntimeError(
                            f"Expected {expected_bytes} bytes for range {range_start}-{end}, "
                            f"got {written} (server may not have honored the Range request)"
                        )
            return
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(backoff_base * (2**attempt))

    raise RuntimeError(f"Chunk download failed after {max_retries} attempts: {last_error}")
