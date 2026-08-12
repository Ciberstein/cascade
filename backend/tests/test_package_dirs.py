"""La carpeta de un paquete sale del nombre que escribe el usuario."""

import os

import pytest

from app.models import Package
from app.package_dirs import target_dir_for
from app.paths import unique_name
from tests.conftest import TEST_OWNER


@pytest.mark.asyncio
async def test_the_folder_is_named_after_the_package(session):
    assert await target_dir_for(session, "/downloads", "Backrooms") == os.path.join("/downloads", "Backrooms")


@pytest.mark.asyncio
async def test_a_hostile_package_name_cannot_escape_the_download_root(session):
    # El nombre lo escribe el usuario. Fase 1 usaba el id generado justamente
    # para no tocar esto; ahora se sanea, que da lo mismo pero legible.
    result = await target_dir_for(session, "/downloads", "../../etc/cron.d")

    assert result == os.path.join("/downloads", "cron.d")


@pytest.mark.asyncio
async def test_an_empty_name_still_produces_a_folder(session):
    assert await target_dir_for(session, "/downloads", "...") == os.path.join("/downloads", "paquete")


@pytest.mark.asyncio
async def test_two_packages_with_the_same_name_do_not_share_a_folder(session, tmp_path):
    session.add(Package(name="Backrooms", status="queued", target_dir=os.path.join("/downloads", "Backrooms"), owner_id=TEST_OWNER))
    await session.commit()

    result = await target_dir_for(session, "/downloads", "Backrooms")

    # Compartir carpeta mezclaría sus archivos y, con nombres iguales, se
    # pisarían entre sí.
    assert result == os.path.join("/downloads", "Backrooms (2)")


def test_unique_name_puts_the_suffix_before_the_extension():
    taken = {"video.mp4"}
    # "video.mp4 (2)" dejaría el archivo sin extensión reconocible.
    assert unique_name("video.mp4", taken) == "video (2).mp4"


def test_unique_name_leaves_a_free_name_alone():
    assert unique_name("video.mp4", set()) == "video.mp4"


def test_unique_name_handles_a_name_without_extension():
    assert unique_name("carpeta", {"carpeta"}) == "carpeta (2)"
