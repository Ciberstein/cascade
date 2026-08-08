import pytest

from app.engine.downloader import download_chunk
from app.engine.item_runner import run_download_item


@pytest.mark.asyncio
async def test_chunk_requests_carry_the_plugin_headers(test_server, tmp_path):
    payload = b"A" * 100
    server, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    await download_chunk(
        url=url, start=0, end=99, dest_path=str(dest), headers={"Cookie": "session=abc"}
    )

    # Muchos hosters devuelven 403 si falta la cookie o el referer que su URL
    # firmada espera; sin esto la descarga fallaría después de resolver bien.
    assert server.seen_headers[-1].get("Cookie") == "session=abc"


@pytest.mark.asyncio
async def test_plugin_headers_do_not_clobber_the_range_header(test_server, tmp_path):
    payload = b"B" * 100
    server, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    await download_chunk(
        url=url, start=10, end=49, dest_path=str(dest), headers={"Range": "bytes=0-999"}
    )

    # Range lo manda el motor de chunks. Que un plugin lo pise rompería la
    # descarga segmentada de forma silenciosa: el archivo quedaría corrupto.
    assert server.requested_ranges[-1] == (10, 49)


@pytest.mark.asyncio
async def test_the_probe_also_carries_the_headers(test_server, tmp_path):
    payload = b"C" * 200
    server, url = await test_server(payload)

    await run_download_item(
        url=url, dest_path=str(tmp_path / "out.bin"), num_chunks=1, headers={"Referer": "http://x/"}
    )

    assert any(h.get("Referer") == "http://x/" for h in server.seen_headers)
