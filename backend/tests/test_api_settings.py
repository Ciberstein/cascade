import pytest


@pytest.mark.asyncio
async def test_get_settings_returns_defaults(auth_client):
    response = auth_client.get("/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["max_concurrent_downloads"] == 3
    assert body["chunks_per_file"] == 4
    assert body["max_speed_kbps"] == 0


@pytest.mark.asyncio
async def test_get_settings_requires_auth(client):
    response = client.get("/settings")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_put_settings_updates_values(auth_client):
    response = auth_client.put(
        "/settings",
        json={
            "download_root": "/downloads",
            "max_concurrent_downloads": 5,
            "chunks_per_file": 8,
            "max_speed_kbps": 2048,
        },
    )

    assert response.status_code == 200
    assert response.json()["max_concurrent_downloads"] == 5

    follow_up = auth_client.get("/settings")
    assert follow_up.json()["chunks_per_file"] == 8


@pytest.mark.asyncio
async def test_put_settings_requires_auth(client):
    response = client.put(
        "/settings",
        json={
            "download_root": "/downloads",
            "max_concurrent_downloads": 5,
            "chunks_per_file": 8,
            "max_speed_kbps": 2048,
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_put_settings_rejects_out_of_bounds_values(auth_client):
    response = auth_client.put(
        "/settings",
        json={
            "download_root": "/downloads",
            "max_concurrent_downloads": 0,
            "chunks_per_file": 8,
            "max_speed_kbps": 2048,
        },
    )
    assert response.status_code == 422

    response = auth_client.put(
        "/settings",
        json={
            "download_root": "/downloads",
            "max_concurrent_downloads": 21,
            "chunks_per_file": 8,
            "max_speed_kbps": 2048,
        },
    )
    assert response.status_code == 422

    response = auth_client.put(
        "/settings",
        json={
            "download_root": "/downloads",
            "max_concurrent_downloads": 5,
            "chunks_per_file": 17,
            "max_speed_kbps": 2048,
        },
    )
    assert response.status_code == 422

    response = auth_client.put(
        "/settings",
        json={
            "download_root": "/downloads",
            "max_concurrent_downloads": 5,
            "chunks_per_file": 8,
            "max_speed_kbps": -1,
        },
    )
    assert response.status_code == 422
