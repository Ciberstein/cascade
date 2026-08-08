import asyncio
import time
from collections.abc import Callable

import httpx

#: How often the output file is flushed and a resumable offset reported.
FLUSH_INTERVAL_SECONDS = 2.0


async def download_chunk(
    url: str,
    start: int,
    end: int,
    dest_path: str,
    max_retries: int = 3,
    backoff_base: float = 0.5,
    resume_from: int = 0,
    on_bytes: Callable[[int], None] | None = None,
    on_flush: Callable[[int], None] | None = None,
    flush_interval_seconds: float = FLUSH_INTERVAL_SECONDS,
) -> None:
    """Download `start`-`end` of `url` into `dest_path` at its true offset.

    on_bytes fires per received block and is only good enough to drive a
    progress bar - those bytes sit in a buffered writer that is not closed
    until the chunk finishes, so they are not on disk yet.

    on_flush is the durable counterpart: the file is flushed first, then the
    callback receives the absolute number of bytes of this chunk that are
    safely written (counting `resume_from`). That value, and only that value,
    is a valid resume point - persisting an on_bytes total instead would let a
    restart resume past bytes the process never flushed, leaving a hole in the
    middle of the file that nothing would ever detect.
    """
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
                    last_flush = time.monotonic()
                    with open(dest_path, "r+b") as f:
                        f.seek(range_start)
                        async for data in response.aiter_bytes():
                            f.write(data)
                            written += len(data)
                            if on_bytes is not None:
                                on_bytes(len(data))

                            now = time.monotonic()
                            if on_flush is not None and now - last_flush >= flush_interval_seconds:
                                f.flush()
                                last_flush = now
                                on_flush(resume_from + written)

                        if on_flush is not None:
                            f.flush()
                            on_flush(resume_from + written)

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
