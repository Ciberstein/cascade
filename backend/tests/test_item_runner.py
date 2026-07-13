import pytest

from app.engine.item_runner import run_download_item


@pytest.mark.asyncio
async def test_run_download_item_downloads_full_file_with_range_support(test_server, tmp_path):
    payload = bytes(range(256)) * 4  # 1024 bytes
    _, url = await test_server(payload, support_range=True)
    dest = tmp_path / "file.bin"

    result = await run_download_item(url=url, dest_path=str(dest), num_chunks=4)

    assert dest.read_bytes() == payload
    assert result.total_size == len(payload)
    assert result.chunk_count == 4


@pytest.mark.asyncio
async def test_run_download_item_falls_back_to_single_chunk_without_range_support(test_server, tmp_path):
    payload = b"X" * 500
    _, url = await test_server(payload, support_range=False)
    dest = tmp_path / "file.bin"

    result = await run_download_item(url=url, dest_path=str(dest), num_chunks=4)

    assert dest.read_bytes() == payload
    assert result.chunk_count == 1


@pytest.mark.asyncio
async def test_run_download_item_handles_zero_byte_file(test_server, tmp_path):
    payload = b""
    _, url = await test_server(payload, support_range=True)
    dest = tmp_path / "file.bin"

    result = await run_download_item(url=url, dest_path=str(dest), num_chunks=4)

    assert dest.read_bytes() == b""
    assert result.total_size == 0
    assert result.chunk_count == 0
