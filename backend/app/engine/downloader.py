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

    if expected_bytes < 0:
        # resume_from is larger than this chunk's size - existing_progress
        # doesn't match this chunk's current boundaries (e.g. num_chunks
        # changed between the run that recorded the progress and this run).
        # Silently skipping would leave a corrupted/incomplete region of the
        # output file with no error raised anywhere, so fail loudly instead.
        raise ValueError(
            f"resume_from={resume_from} exceeds the size of range {start}-{end} "
            f"({end - start + 1} bytes) - existing_progress may not match this chunk's "
            f"current boundaries (e.g. num_chunks changed between the run that recorded "
            f"this progress and this run)"
        )
    if expected_bytes == 0:
        # resume_from exactly covers the whole chunk - already fully
        # downloaded by a prior attempt, nothing left to fetch.
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
        except (httpx.HTTPError, RuntimeError) as exc:
            # Only network/HTTP errors and this function's own validation
            # RuntimeErrors should trigger a retry. Anything else - notably
            # an exception raised by a caller-supplied on_bytes callback -
            # is a bug in the caller, not a transient download failure, and
            # must propagate immediately with its original type intact
            # rather than being retried and buried under a generic
            # "Chunk download failed" RuntimeError.
            last_error = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(backoff_base * (2**attempt))

    raise RuntimeError(f"Chunk download failed after {max_retries} attempts: {last_error}")
