import asyncio
from dataclasses import dataclass

import httpx

from app.engine.chunker import split_into_chunks
from app.engine.downloader import download_chunk


@dataclass
class ItemResult:
    total_size: int
    chunk_count: int


async def _probe(url: str) -> tuple[int, bool]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.head(url)
        total_size = int(response.headers.get("Content-Length", 0))
        supports_range = response.headers.get("Accept-Ranges") == "bytes"
        return total_size, supports_range


async def run_download_item(url: str, dest_path: str, num_chunks: int) -> ItemResult:
    total_size, supports_range = await _probe(url)
    effective_chunks = num_chunks if supports_range else 1

    with open(dest_path, "wb") as f:
        f.truncate(total_size)

    ranges = split_into_chunks(total_size, effective_chunks)
    await asyncio.gather(
        *(download_chunk(url=url, start=s, end=e, dest_path=dest_path) for s, e in ranges)
    )

    return ItemResult(total_size=total_size, chunk_count=len(ranges))
