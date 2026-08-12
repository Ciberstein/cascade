"""Unir las pistas separadas es lo que hace que elegir calidad tenga sentido.

Sin este paso, la única calidad descargable de YouTube sería 360p: de sus 33
formatos es el único que trae video y audio juntos.
"""

import pytest
from sqlalchemy import select

from app.engine.merge import merge_ready_groups, part_suffix
from app.models import DownloadItem, Package
from tests.conftest import TEST_OWNER


def test_each_part_downloads_under_its_own_name():
    # Las dos partes y el resultado viven en la misma carpeta: sin sufijo se
    # pisarían entre sí.
    assert part_suffix("video") == ".part-video"
    assert part_suffix("audio") == ".part-audio"
    assert part_suffix(None) == ""


async def _group(session, tmp_path, *, audio_status="completed"):
    package = Package(name="pkg", status="running", target_dir=str(tmp_path), owner_id=TEST_OWNER)
    session.add(package)
    await session.flush()
    video = DownloadItem(
        package_id=package.id, url="http://x/v", filename="video.mp4", status="completed",
        hoster="ytdlp", merge_group="g1", merge_role="video", downloaded_bytes=100, total_size=100,
    )
    audio = DownloadItem(
        package_id=package.id, url="http://x/v", filename="video.mp4", status=audio_status,
        hoster="ytdlp", merge_group="g1", merge_role="audio", downloaded_bytes=10, total_size=10,
    )
    session.add_all([video, audio])
    await session.commit()
    return package, video, audio


@pytest.mark.asyncio
async def test_a_group_waits_until_both_parts_are_done(session, tmp_path):
    await _group(session, tmp_path, audio_status="running")

    assert await merge_ready_groups(session) == 0
    # Unir con una pista a medio bajar daría un archivo truncado.
    assert len((await session.execute(select(DownloadItem))).scalars().all()) == 2


@pytest.mark.asyncio
async def test_a_failed_merge_fails_the_item_instead_of_leaving_it_limbo(session, tmp_path, monkeypatch):
    _, video, _ = await _group(session, tmp_path)

    async def boom(*args, **kwargs):
        raise RuntimeError("ffmpeg no está")

    import app.engine.merge as merge_mod

    monkeypatch.setattr(merge_mod, "_merge", boom)

    await merge_ready_groups(session)

    await session.refresh(video)
    # Sin esto el grupo se reintentaría en cada tick para siempre, y el paquete
    # nunca llegaría a un estado final.
    assert video.status == "error"
    assert "unir" in video.error_message


@pytest.mark.asyncio
async def test_merging_leaves_one_item_that_owns_the_whole_size(session, tmp_path, monkeypatch):
    _, video, audio = await _group(session, tmp_path)

    async def fake_merge(target_dir, v, a):
        (tmp_path / "video.mp4").write_bytes(b"unido")

    import app.engine.merge as merge_mod

    monkeypatch.setattr(merge_mod, "_merge", fake_merge)

    assert await merge_ready_groups(session) == 1

    remaining = (await session.execute(select(DownloadItem))).scalars().all()
    # La parte de audio deja de existir: era un medio, no una descarga que el
    # usuario pidió, y mostrarla sería confuso.
    assert len(remaining) == 1
    assert remaining[0].merge_group is None
    assert remaining[0].merge_role is None
    # El tamaño del resultado es el de las dos pistas juntas.
    assert remaining[0].total_size == 110
    assert remaining[0].downloaded_bytes == 110


@pytest.mark.asyncio
async def test_an_already_merged_item_is_not_merged_again(session, tmp_path, monkeypatch):
    await _group(session, tmp_path)

    async def fake_merge(target_dir, v, a):
        pass

    import app.engine.merge as merge_mod

    monkeypatch.setattr(merge_mod, "_merge", fake_merge)
    await merge_ready_groups(session)

    assert await merge_ready_groups(session) == 0
