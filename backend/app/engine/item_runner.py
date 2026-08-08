import asyncio
import inspect
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.engine.chunker import split_into_chunks
from app.engine.downloader import FLUSH_INTERVAL_SECONDS, download_chunk


@dataclass
class ItemResult:
    total_size: int
    chunk_count: int


async def _probe(url: str) -> tuple[int, bool]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.head(url)
        response.raise_for_status()

        content_length = response.headers.get("Content-Length")
        if content_length is None:
            raise RuntimeError(f"Server did not return a Content-Length header for {url}")

        total_size = int(content_length)
        supports_range = response.headers.get("Accept-Ranges") == "bytes"
        return total_size, supports_range


async def run_download_item(
    url: str,
    dest_path: str,
    num_chunks: int,
    existing_progress: dict[int, int] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_chunks_planned: Callable[[list[tuple[int, int]]], Awaitable[None] | None] | None = None,
    on_checkpoint: Callable[[int, int], None] | None = None,
    flush_interval_seconds: float = FLUSH_INTERVAL_SECONDS,
) -> ItemResult:
    """Download `url` to `dest_path`, optionally resuming from prior progress.

    existing_progress maps chunk index -> bytes already downloaded for that
    chunk. Chunk indices are positional (0-based, matching the order
    split_into_chunks returns ranges in), NOT stable identifiers - they are
    only meaningful for the same num_chunks that produced them. If num_chunks
    changes between the run that recorded existing_progress and this run,
    the chunk boundaries shift and the recorded progress no longer lines up;
    passing such stale progress will raise ValueError out of download_chunk
    for any chunk where resume_from exceeds the (re-split) chunk's size.
    Callers that persist progress across process restarts (e.g. a future
    scheduler) must keep num_chunks fixed for the lifetime of an item, or
    discard existing_progress when num_chunks changes.

    on_checkpoint(index, durable_bytes) reports, per chunk, how many of its
    bytes are flushed to disk. Persisting those values is what makes
    existing_progress non-zero on the next run - i.e. what turns a restart
    into a resume rather than a fresh download.
    """
    total_size, supports_range = await _probe(url)
    effective_chunks = num_chunks if supports_range else 1

    open_mode = "r+b" if os.path.exists(dest_path) else "wb"
    with open(dest_path, open_mode) as f:
        f.truncate(total_size)

    ranges = split_into_chunks(total_size, effective_chunks)

    if on_chunks_planned is not None:
        maybe_awaitable = on_chunks_planned(ranges)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable

    existing_progress = existing_progress or {}

    async def _run_chunk(index: int, s: int, e: int) -> None:
        resume_from = existing_progress.get(index, 0)

        def _on_bytes(n: int) -> None:
            if on_progress is not None:
                on_progress(index, n)

        def _on_flush(durable_bytes: int) -> None:
            if on_checkpoint is not None:
                on_checkpoint(index, durable_bytes)

        await download_chunk(
            url=url,
            start=s,
            end=e,
            dest_path=dest_path,
            resume_from=resume_from,
            on_bytes=_on_bytes if on_progress is not None else None,
            on_flush=_on_flush if on_checkpoint is not None else None,
            flush_interval_seconds=flush_interval_seconds,
        )

    await asyncio.gather(
        *(_run_chunk(i, s, e) for i, (s, e) in enumerate(ranges))
    )

    return ItemResult(total_size=total_size, chunk_count=len(ranges))
