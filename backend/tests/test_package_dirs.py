"""A package's folder comes from the name the user types."""

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
    # The user writes the name. Phase 1 used the generated id precisely to
    # avoid touching this; now it is sanitised, which is just as safe but
    # readable.
    result = await target_dir_for(session, "/downloads", "../../etc/cron.d")

    assert result == os.path.join("/downloads", "cron.d")


@pytest.mark.asyncio
async def test_an_empty_name_still_produces_a_folder(session):
    assert await target_dir_for(session, "/downloads", "...") == os.path.join("/downloads", "package")


@pytest.mark.asyncio
async def test_two_packages_with_the_same_name_do_not_share_a_folder(session, tmp_path):
    session.add(Package(name="Backrooms", status="queued", target_dir=os.path.join("/downloads", "Backrooms"), owner_id=TEST_OWNER))
    await session.commit()

    result = await target_dir_for(session, "/downloads", "Backrooms")

    # Sharing a folder would mix their files and, with identical names, they
    # would overwrite each other.
    assert result == os.path.join("/downloads", "Backrooms (2)")


def test_unique_name_puts_the_suffix_before_the_extension():
    taken = {"video.mp4"}
    # "video.mp4 (2)" would leave the file with no recognisable extension.
    assert unique_name("video.mp4", taken) == "video (2).mp4"


def test_unique_name_leaves_a_free_name_alone():
    assert unique_name("video.mp4", set()) == "video.mp4"


def test_unique_name_handles_a_name_without_extension():
    assert unique_name("folder", {"folder"}) == "folder (2)"
