"""El servidor no acumula: libera lo que ya cumplió."""

import datetime as dt

import pytest

from app.models import DownloadItem, Package
from app.retention import sweep
from tests.conftest import TEST_OWNER


async def _item(session, tmp_path, *, retrieved_ago=None, created_ago=None, name="a.bin"):
    created = dt.datetime.utcnow() - (created_ago or dt.timedelta(0))
    package = Package(
        name="pkg", status="completed", target_dir=str(tmp_path), owner_id=TEST_OWNER, created_at=created
    )
    session.add(package)
    await session.flush()
    item = DownloadItem(
        package_id=package.id, url="http://x/a", filename=name, status="completed", hoster="direct",
        retrieved_at=None if retrieved_ago is None else dt.datetime.utcnow() - retrieved_ago,
    )
    session.add(item)
    await session.commit()
    (tmp_path / name).write_bytes(b"bytes")
    return item


@pytest.mark.asyncio
async def test_a_retrieved_file_is_freed_after_the_grace_period(session, tmp_path):
    item = await _item(session, tmp_path, retrieved_ago=dt.timedelta(hours=2))

    freed = await sweep(session, grace_minutes=30, max_retention_hours=24)

    assert freed == 1
    assert not (tmp_path / "a.bin").exists()
    await session.refresh(item)
    assert item.file_removed_at is not None
    # La fila queda: lo que se va es el archivo, no el historial.
    assert item.status == "completed"


@pytest.mark.asyncio
async def test_a_just_retrieved_file_is_kept_during_the_grace_period(session, tmp_path):
    await _item(session, tmp_path, retrieved_ago=dt.timedelta(minutes=1))

    freed = await sweep(session, grace_minutes=30, max_retention_hours=24)

    # Si la descarga del navegador se corta al 90%, borrarlo al instante
    # dejaría al usuario sin nada.
    assert freed == 0
    assert (tmp_path / "a.bin").exists()


@pytest.mark.asyncio
async def test_a_file_nobody_retrieved_is_freed_once_it_ages_out(session, tmp_path):
    await _item(session, tmp_path, created_ago=dt.timedelta(days=3))

    freed = await sweep(session, grace_minutes=30, max_retention_hours=24)

    # Sin este tope, lo que nadie va a buscar se queda para siempre y el disco
    # vuelve a crecer.
    assert freed == 1
    assert not (tmp_path / "a.bin").exists()


@pytest.mark.asyncio
async def test_a_recent_unretrieved_file_is_left_alone(session, tmp_path):
    await _item(session, tmp_path)

    freed = await sweep(session, grace_minutes=30, max_retention_hours=24)

    assert freed == 0
    assert (tmp_path / "a.bin").exists()


@pytest.mark.asyncio
async def test_an_already_freed_file_is_not_swept_again(session, tmp_path):
    item = await _item(session, tmp_path, retrieved_ago=dt.timedelta(hours=2))
    await sweep(session, grace_minutes=30, max_retention_hours=24)

    freed = await sweep(session, grace_minutes=30, max_retention_hours=24)

    assert freed == 0
    await session.refresh(item)
    assert item.file_removed_at is not None


@pytest.mark.asyncio
async def test_a_missing_file_is_marked_instead_of_retried_forever(session, tmp_path):
    item = await _item(session, tmp_path, retrieved_ago=dt.timedelta(hours=2))
    (tmp_path / "a.bin").unlink()

    await sweep(session, grace_minutes=30, max_retention_hours=24)

    await session.refresh(item)
    assert item.file_removed_at is not None


@pytest.mark.asyncio
async def test_a_download_still_running_is_never_touched(session, tmp_path):
    package = Package(name="pkg", status="running", target_dir=str(tmp_path), owner_id=TEST_OWNER,
                      created_at=dt.datetime.utcnow() - dt.timedelta(days=5))
    session.add(package)
    await session.flush()
    session.add(DownloadItem(package_id=package.id, url="http://x/a", filename="a.bin",
                             status="running", hoster="direct"))
    await session.commit()
    (tmp_path / "a.bin").write_bytes(b"a medio bajar")

    freed = await sweep(session, grace_minutes=30, max_retention_hours=24)

    # Borrarlo a mitad de la descarga le sacaría el archivo al motor de abajo
    # de los pies, con los chunks escribiendo en él.
    assert freed == 0
    assert (tmp_path / "a.bin").exists()
