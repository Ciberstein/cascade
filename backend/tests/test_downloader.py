import pytest

from app.engine.downloader import download_chunk


@pytest.mark.asyncio
async def test_download_chunk_writes_correct_bytes(test_server, tmp_path):
    payload = b"0123456789" * 100  # 1000 bytes
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    await download_chunk(url=url, start=100, end=199, dest_path=str(dest))

    with open(dest, "rb") as f:
        f.seek(100)
        written = f.read(100)
    assert written == payload[100:200]


@pytest.mark.asyncio
async def test_download_chunk_retries_on_transient_failure(test_server, tmp_path):
    payload = b"A" * 500
    _, url = await test_server(payload, fail_first_n=2)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    await download_chunk(url=url, start=0, end=499, dest_path=str(dest), max_retries=3, backoff_base=0.01)

    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_chunk_raises_after_exhausting_retries(test_server, tmp_path):
    payload = b"A" * 100
    _, url = await test_server(payload, fail_first_n=10)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    with pytest.raises(RuntimeError):
        await download_chunk(url=url, start=0, end=99, dest_path=str(dest), max_retries=2, backoff_base=0.01)


@pytest.mark.asyncio
async def test_download_chunk_raises_when_server_ignores_range(test_server, tmp_path):
    # Server advertises range support but returns the full payload with
    # status 200 regardless of the Range header - the downloader must detect
    # the byte-count mismatch rather than silently writing the wrong bytes
    # into the destination file at the requested offset.
    payload = b"0123456789" * 100  # 1000 bytes
    _, url = await test_server(payload, ignore_range=True)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    with pytest.raises(RuntimeError):
        await download_chunk(
            url=url, start=100, end=199, dest_path=str(dest), max_retries=1, backoff_base=0.01
        )


@pytest.mark.asyncio
async def test_download_chunk_resumes_from_offset(test_server, tmp_path):
    payload = b"A" * 200 + b"B" * 300  # 500 bytes total
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(payload[:200] + b"\x00" * 300)  # first 200 bytes already on disk

    await download_chunk(url=url, start=0, end=499, dest_path=str(dest), resume_from=200)

    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_chunk_calls_progress_callback(test_server, tmp_path):
    payload = b"A" * 1000
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))
    seen: list[int] = []

    await download_chunk(
        url=url, start=0, end=999, dest_path=str(dest), on_bytes=lambda n: seen.append(n)
    )

    assert sum(seen) == 1000


@pytest.mark.asyncio
async def test_download_chunk_skips_request_when_already_fully_resumed(test_server, tmp_path):
    payload = b"A" * 100
    # fail_first_n set far higher than max_retries: if download_chunk made
    # any HTTP request at all, every attempt would 503 and the call would
    # raise RuntimeError after exhausting retries. A clean return proves no
    # request was made.
    _, url = await test_server(payload, fail_first_n=1000)
    dest = tmp_path / "out.bin"
    dest.write_bytes(payload)
    seen: list[int] = []

    await download_chunk(
        url=url,
        start=0,
        end=99,
        dest_path=str(dest),
        resume_from=100,
        max_retries=2,
        backoff_base=0.01,
        on_bytes=lambda n: seen.append(n),
    )

    assert dest.read_bytes() == payload
    assert seen == []


@pytest.mark.asyncio
async def test_download_chunk_raises_value_error_when_resume_from_exceeds_chunk_size(
    test_server, tmp_path
):
    payload = b"A" * 100
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(payload)

    with pytest.raises(ValueError, match="resume_from"):
        await download_chunk(url=url, start=0, end=99, dest_path=str(dest), resume_from=101)
