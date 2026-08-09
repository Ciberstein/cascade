"""Entregar el archivo al navegador es lo que hace que el usuario lo reciba.

Cascade descarga al disco del servidor; sin este endpoint el archivo se queda
ahí y el usuario no tiene forma de obtenerlo.
"""

import pytest

from app.models import DownloadItem, Package
from tests.conftest import TEST_OWNER

OTHER_OWNER = "otroowner0000000000000000000000b"


async def _completed(session, tmp_path, status="completed", write=True):
    package = Package(name="pkg", status="completed", target_dir=str(tmp_path), owner_id=TEST_OWNER)
    session.add(package)
    await session.flush()
    item = DownloadItem(
        package_id=package.id, url="http://x/a", filename="video.mp4",
        status=status, hoster="direct", downloaded_bytes=5, total_size=5,
    )
    session.add(item)
    await session.commit()
    if write:
        (tmp_path / "video.mp4").write_bytes(b"hola!")
    return package, item


@pytest.mark.asyncio
async def test_a_finished_file_is_handed_to_the_browser(async_auth_client, session, tmp_path):
    package, item = await _completed(session, tmp_path)

    response = await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    assert response.status_code == 200
    assert response.content == b"hola!"
    # Content-Disposition es lo que hace que el navegador lo guarde en su
    # carpeta de descargas en vez de mostrarlo.
    assert "attachment" in response.headers["content-disposition"]
    assert "video.mp4" in response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_an_unfinished_file_is_refused(async_auth_client, session, tmp_path):
    package, item = await _completed(session, tmp_path, status="running")

    response = await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    # El archivo existe pero está a medio escribir: entregarlo daría algo
    # corrupto con apariencia de bueno.
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_a_file_deleted_from_the_server_says_so(async_auth_client, session, tmp_path):
    package, item = await _completed(session, tmp_path, write=False)

    response = await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    assert response.status_code == 410


@pytest.mark.asyncio
async def test_one_browser_cannot_download_another_browsers_file(async_auth_client, session, tmp_path):
    package, item = await _completed(session, tmp_path)

    async_auth_client.headers["X-Cascade-Owner"] = OTHER_OWNER
    response = await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    # 404 y no 403: no confirma siquiera que ese archivo exista.
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_an_item_from_another_package_is_not_reachable(async_auth_client, session, tmp_path):
    _, item = await _completed(session, tmp_path)
    otro = Package(name="otro", status="queued", target_dir=str(tmp_path), owner_id=TEST_OWNER)
    session.add(otro)
    await session.commit()

    response = await async_auth_client.get(f"/packages/{otro.id}/items/{item.id}/file")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_tampered_filename_cannot_serve_a_file_outside_the_package(
    async_auth_client, session, tmp_path
):
    package, item = await _completed(session, tmp_path)
    secreto = tmp_path.parent / "secreto.txt"
    secreto.write_bytes(b"ajeno")

    # Simula una fila manipulada: la ruta se recalcula con contención en vez de
    # confiar en lo guardado.
    item.filename = "../secreto.txt"
    await session.commit()

    response = await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    assert response.content != b"ajeno"


@pytest.mark.asyncio
async def test_the_first_retrieval_starts_the_clock(async_auth_client, session, tmp_path):
    package, item = await _completed(session, tmp_path)

    await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    await session.refresh(item)
    assert item.retrieved_at is not None


@pytest.mark.asyncio
async def test_retrying_does_not_postpone_the_release(async_auth_client, session, tmp_path):
    package, item = await _completed(session, tmp_path)

    await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")
    await session.refresh(item)
    primero = item.retrieved_at

    await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    await session.refresh(item)
    # Contar desde el último retiro dejaría postergar la liberación sin fin.
    assert item.retrieved_at == primero


@pytest.mark.asyncio
async def test_a_released_file_says_so_instead_of_failing_obscurely(async_auth_client, session, tmp_path):
    import datetime as dt

    package, item = await _completed(session, tmp_path)
    item.file_removed_at = dt.datetime.utcnow()
    await session.commit()

    response = await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    assert response.status_code == 410
    assert "ya no está en el servidor" in response.json()["detail"]


@pytest.mark.asyncio
async def test_deleting_a_package_frees_its_files(async_auth_client, session, tmp_path):
    package, _ = await _completed(session, tmp_path)

    await async_auth_client.delete(f"/packages/{package.id}")

    # Acá sí se borran, al revés que en un gestor que guarda: el servidor es un
    # lugar de paso y la copia del usuario está en su equipo.
    assert not (tmp_path / "video.mp4").exists()


@pytest.mark.asyncio
async def test_the_file_is_released_as_soon_as_it_is_delivered(async_auth_client, session, tmp_path):
    """El servidor no lo conserva ni un minuto de más.

    Va como tarea de fondo: corre recién cuando la respuesta terminó de
    enviarse. Si el navegador corta a mitad no llega a correr y el archivo
    queda para reintentar, que es lo que hay que preservar cuando la descarga
    se dispara sola y nadie está mirando.
    """
    package, item = await _completed(session, tmp_path)

    response = await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    assert response.content == b"hola!"
    assert not (tmp_path / "video.mp4").exists()


@pytest.mark.asyncio
async def test_a_delivered_item_says_it_was_retrieved(async_auth_client, session, tmp_path):
    package, item = await _completed(session, tmp_path)

    await async_auth_client.get(f"/packages/{package.id}/items/{item.id}/file")

    body = (await async_auth_client.get("/packages")).json()
    entregado = body[0]["items"][0]
    # Es lo que evita que el navegador vuelva a dispararla sola en cada sondeo.
    assert entregado["retrieved"] is True
