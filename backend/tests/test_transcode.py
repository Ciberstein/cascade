"""Extracting the soundtrack is a download plus a conversion.

The conversion is its own pass over the database rather than a step tacked onto
the download, so a restart between the last byte and ffmpeg finishing does not
lose the fact that a file is still owed.
"""

import os

import pytest
from sqlalchemy import select

from app.engine.transcode import convert_ready_items
from app.models import DownloadItem, Package
from tests.conftest import TEST_OWNER


async def _item(session, tmp_path, *, status="completed", postprocess="mp3"):
    package = Package(name="pkg", status="running", target_dir=str(tmp_path), owner_id=TEST_OWNER)
    session.add(package)
    await session.flush()
    item = DownloadItem(
        package_id=package.id, url="http://x/v", filename="song.mp3", status=status,
        hoster="ytdlp", postprocess=postprocess, downloaded_bytes=10, total_size=10,
    )
    session.add(item)
    await session.commit()
    (tmp_path / "song.mp3").write_bytes(b"not really audio")
    return item


@pytest.mark.asyncio
async def test_a_download_still_running_is_left_alone(session, tmp_path):
    await _item(session, tmp_path, status="running")

    # Transcoding a file that is still being written would read a truncated
    # track and call the result finished.
    assert await convert_ready_items(session) == 0


@pytest.mark.asyncio
async def test_a_file_nobody_asked_to_convert_is_untouched(session, tmp_path):
    await _item(session, tmp_path, postprocess=None)

    assert await convert_ready_items(session) == 0


@pytest.mark.asyncio
async def test_converting_clears_the_debt_and_resizes_the_row(session, tmp_path, monkeypatch):
    item = await _item(session, tmp_path)

    async def fake(target_dir, filename):
        (tmp_path / filename).write_bytes(b"x" * 4096)

    import app.engine.transcode as transcode

    monkeypatch.setattr(transcode, "_to_mp3", fake)

    assert await convert_ready_items(session) == 1

    await session.refresh(item)
    # Cleared, or the next tick would convert an already-converted file.
    assert item.postprocess is None
    # The file on disk changed size underneath the row that the progress bar
    # and the retention sweep both read.
    assert item.total_size == 4096
    assert item.downloaded_bytes == 4096


@pytest.mark.asyncio
async def test_a_failed_conversion_fails_the_item_instead_of_looping(session, tmp_path, monkeypatch):
    item = await _item(session, tmp_path)

    async def boom(target_dir, filename):
        raise RuntimeError("ffmpeg is not here")

    import app.engine.transcode as transcode

    monkeypatch.setattr(transcode, "_to_mp3", boom)

    await convert_ready_items(session)

    await session.refresh(item)
    assert item.status == "error"
    assert "extract the audio" in item.error_message
    # Cleared even on failure: left set, every later tick would retry a file
    # ffmpeg has already refused, forever.
    assert item.postprocess is None


@pytest.mark.asyncio
async def test_one_bad_file_does_not_stop_the_others(session, tmp_path, monkeypatch):
    good = await _item(session, tmp_path)
    bad = DownloadItem(
        package_id=good.package_id, url="http://x/w", filename="broken.mp3",
        status="completed", hoster="ytdlp", postprocess="mp3",
        downloaded_bytes=5, total_size=5,
    )
    session.add(bad)
    await session.commit()

    async def selective(target_dir, filename):
        if filename == "broken.mp3":
            raise RuntimeError("nope")
        (tmp_path / filename).write_bytes(b"ok")

    import app.engine.transcode as transcode

    monkeypatch.setattr(transcode, "_to_mp3", selective)

    assert await convert_ready_items(session) == 1

    await session.refresh(bad)
    assert bad.status == "error"


@pytest.mark.asyncio
async def test_the_conversion_never_writes_over_its_own_input(session, tmp_path):
    # ffmpeg cannot read and write the same path. The real _to_mp3 goes through
    # a neighbouring file and swaps at the end; this pins that down, because
    # the failure mode is a truncated file that every later step trusts.
    await _item(session, tmp_path)
    import app.engine.transcode as transcode
    import inspect

    source = inspect.getsource(transcode._to_mp3)
    assert "os.replace" in source
    assert ".transcoding" in source
