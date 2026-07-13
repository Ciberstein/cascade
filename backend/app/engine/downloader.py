import asyncio

import httpx


async def download_chunk(
    url: str,
    start: int,
    end: int,
    dest_path: str,
    max_retries: int = 3,
    backoff_base: float = 0.5,
) -> None:
    expected_bytes = end - start + 1
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Range": f"bytes={start}-{end}"}
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code not in (200, 206):
                        raise RuntimeError(f"Unexpected status {response.status_code}")

                    written = 0
                    with open(dest_path, "r+b") as f:
                        f.seek(start)
                        async for data in response.aiter_bytes():
                            f.write(data)
                            written += len(data)

                    if written != expected_bytes:
                        raise RuntimeError(
                            f"Expected {expected_bytes} bytes for range {start}-{end}, "
                            f"got {written} (server may not have honored the Range request)"
                        )
            return
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(backoff_base * (2**attempt))

    raise RuntimeError(f"Chunk download failed after {max_retries} attempts: {last_error}")
