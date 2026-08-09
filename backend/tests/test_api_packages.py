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

