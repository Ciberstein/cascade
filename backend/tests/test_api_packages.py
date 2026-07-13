import pytest


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
async def test_create_package_requires_auth(client):
    response = client.post("/packages", json={"name": "x", "urls": ["https://example.com/a.zip"]})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_package_rejects_empty_urls(auth_client):
    response = auth_client.post("/packages", json={"name": "x", "urls": []})
    assert response.status_code == 422
