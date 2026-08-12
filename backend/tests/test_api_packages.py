import os

import pytest

from app.config import Settings


@pytest.mark.asyncio
async def test_create_package(auth_client):
    response = auth_client.post(
        "/packages",
        json={
            "name": "My package",
            "urls": ["https://example.com/a.zip", "https://example.com/b.zip"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "My package"
    assert body["status"] == "queued"
    assert len(body["items"]) == 2
    assert body["items"][0]["url"] == "https://example.com/a.zip"
    assert body["items"][0]["status"] == "queued"


@pytest.mark.asyncio
async def test_creating_a_package_requires_an_owner_token(client):
    # Sin login, pero tampoco anónimo del todo: sin dueño no hay a quién
    # atribuirle el paquete.
    client.headers.pop("X-Cascade-Owner", None)

    response = client.post("/packages", json={"name": "p", "urls": ["http://x/a"]})
    assert response.status_code == 400


def test_one_browser_never_sees_another_browsers_packages(auth_client):
    auth_client.post("/packages", json={"name": "mio", "urls": ["http://x/a"]})

    auth_client.headers["X-Cascade-Owner"] = "otroowner0000000000000000000000b"
    ajenos = auth_client.get("/packages").json()

    assert ajenos == []



def test_a_browser_navigation_identifies_itself_with_the_cookie(client):
    """Una descarga es una navegación, no una llamada de API.

    Un <a download> no puede mandar cabeceras propias, así que sin aceptar la
    cookie el endpoint que entrega el archivo respondía 400 y el navegador
    mostraba "error desconocido en el servidor".
    """
    from tests.conftest import TEST_OWNER

    client.headers.pop("X-Cascade-Owner", None)
    client.cookies.set("cascade_owner", TEST_OWNER)

    assert client.get("/packages").status_code == 200


def test_the_header_still_wins_when_both_are_present(client):
    from tests.conftest import TEST_OWNER

    client.cookies.set("cascade_owner", "otroowner0000000000000000000000b")
    client.headers["X-Cascade-Owner"] = TEST_OWNER

    # El cliente de API es explícito; la cookie es el respaldo para navegaciones.
    assert client.get("/packages").status_code == 200
