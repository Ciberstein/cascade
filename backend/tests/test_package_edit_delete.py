"""Renombrar y eliminar un paquete de la lista."""

import pytest
from sqlalchemy import select

from app.models import Chunk, DownloadItem, Package
from tests.conftest import TEST_OWNER

OTHER_OWNER = "otroowner0000000000000000000000b"


async def _seed(session, tmp_path, item_status="queued"):
    package = Package(name="viejo", status="queued", target_dir=str(tmp_path), owner_id=TEST_OWNER)
    session.add(package)
    await session.flush()
    item = DownloadItem(
        package_id=package.id, url="http://x/a", filename="a.bin", status=item_status, hoster="direct"
    )
    session.add(item)
    await session.flush()
    session.add(Chunk(download_item_id=item.id, range_start=0, range_end=9, status="completed"))
    await session.commit()
    return package


@pytest.mark.asyncio
async def test_a_package_can_be_renamed(async_auth_client, session, tmp_path):
    package = await _seed(session, tmp_path)

    body = (await async_auth_client.patch(f"/packages/{package.id}", json={"name": "nuevo"})).json()

    assert body["name"] == "nuevo"


@pytest.mark.asyncio
async def test_renaming_does_not_move_the_files_on_disk(async_auth_client, session, tmp_path):
    package = await _seed(session, tmp_path)
    original_dir = package.target_dir

    body = (await async_auth_client.patch(f"/packages/{package.id}", json={"name": "nuevo"})).json()

    # Mover la carpeta a mitad de una descarga rompería las escrituras en curso.
    assert body["target_dir"] == original_dir


@pytest.mark.asyncio
async def test_status_and_name_can_change_together(async_auth_client, session, tmp_path):
    package = await _seed(session, tmp_path)

    body = (await async_auth_client.patch(
        f"/packages/{package.id}", json={"name": "nuevo", "status": "paused"}
    )).json()

    assert (body["name"], body["status"]) == ("nuevo", "paused")


@pytest.mark.asyncio
async def test_an_empty_patch_changes_nothing(async_auth_client, session, tmp_path):
    package = await _seed(session, tmp_path)

    body = (await async_auth_client.patch(f"/packages/{package.id}", json={})).json()

    assert (body["name"], body["status"]) == ("viejo", "queued")


@pytest.mark.asyncio
async def test_deleting_removes_the_package_with_its_items_and_chunks(async_auth_client, session, tmp_path):
    package = await _seed(session, tmp_path)

    response = await async_auth_client.delete(f"/packages/{package.id}")

    assert response.status_code == 204
    assert (await session.execute(select(Package))).scalars().all() == []
    # Sin la cascada quedarían items y chunks huérfanos que nadie vuelve a mirar.
    assert (await session.execute(select(DownloadItem))).scalars().all() == []
    assert (await session.execute(select(Chunk))).scalars().all() == []


@pytest.mark.asyncio
async def test_deleting_frees_the_file_from_the_server(async_auth_client, session, tmp_path):
    """Cambió respecto de un gestor que guarda.

    Antes eliminar dejaba el archivo, como cuando un navegador borra una
    descarga de su historial. Pero el servidor pasó a ser un lugar de paso: la
    copia del usuario está en su equipo, y dejar la del servidor sería
    exactamente la acumulación que se quiere evitar.
    """
    package = await _seed(session, tmp_path)
    archivo = tmp_path / "a.bin"
    archivo.write_bytes(b"copia del servidor")

    await async_auth_client.delete(f"/packages/{package.id}")

    assert not archivo.exists()


@pytest.mark.asyncio
async def test_a_package_with_a_running_item_is_not_deleted(async_auth_client, session, tmp_path):
    package = await _seed(session, tmp_path, item_status="running")

    response = await async_auth_client.delete(f"/packages/{package.id}")

    # El motor tiene archivos abiertos y seguiría escribiendo checkpoints sobre
    # filas que ya no existirían.
    assert response.status_code == 409
    assert (await session.execute(select(Package))).scalar_one() is not None


@pytest.mark.asyncio
async def test_one_browser_cannot_delete_another_browsers_package(async_auth_client, session, tmp_path):
    package = await _seed(session, tmp_path)

    async_auth_client.headers["X-Cascade-Owner"] = OTHER_OWNER
    response = await async_auth_client.delete(f"/packages/{package.id}")

    # 404 y no 403: no confirma siquiera que ese paquete exista.
    assert response.status_code == 404
    assert (await session.execute(select(Package))).scalar_one() is not None


@pytest.mark.asyncio
async def test_one_browser_cannot_rename_another_browsers_package(async_auth_client, session, tmp_path):
    package = await _seed(session, tmp_path)

    async_auth_client.headers["X-Cascade-Owner"] = OTHER_OWNER
    response = await async_auth_client.patch(f"/packages/{package.id}", json={"name": "robado"})

    assert response.status_code == 404
