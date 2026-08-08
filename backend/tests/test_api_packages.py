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
async def test_create_package_requires_auth(client):
    response = client.post("/packages", json={"name": "x", "urls": ["https://example.com/a.zip"]})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_package_rejects_empty_urls(auth_client):
    response = auth_client.post("/packages", json={"name": "x", "urls": []})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_package_target_dir_is_safe_even_with_malicious_name(auth_client):
    response = auth_client.post(
        "/packages",
        json={"name": "../../etc/passwd", "urls": ["https://example.com/a.zip"]},
    )

    assert response.status_code == 201
    body = response.json()
    target_dir = body["target_dir"]
    download_root = Settings().download_root

    # must stay confined under download_root, keyed by the generated id --
    # never derived from (and never escaping via) the user-supplied name.
    assert ".." not in target_dir
    assert target_dir == os.path.join(download_root, body["id"])


@pytest.mark.asyncio
async def test_list_packages(auth_client):
    auth_client.post("/packages", json={"name": "Pkg A", "urls": ["https://example.com/a.zip"]})
    auth_client.post("/packages", json={"name": "Pkg B", "urls": ["https://example.com/b.zip"]})

    response = auth_client.get("/packages")

    assert response.status_code == 200
    names = {pkg["name"] for pkg in response.json()}
    assert names == {"Pkg A", "Pkg B"}


@pytest.mark.asyncio
async def test_list_packages_requires_auth(client):
    response = client.get("/packages")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_package_status(auth_client):
    create = auth_client.post("/packages", json={"name": "Pkg", "urls": ["https://example.com/a.zip"]})
    package_id = create.json()["id"]

    response = auth_client.patch(f"/packages/{package_id}", json={"status": "paused"})

    assert response.status_code == 200
    assert response.json()["status"] == "paused"


@pytest.mark.asyncio
async def test_patch_package_rejects_invalid_status(auth_client):
    create = auth_client.post("/packages", json={"name": "Pkg", "urls": ["https://example.com/a.zip"]})
    package_id = create.json()["id"]

    response = auth_client.patch(f"/packages/{package_id}", json={"status": "bogus"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_package_404_for_unknown_id(auth_client):
    response = auth_client.patch("/packages/does-not-exist", json={"status": "paused"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_patch_package_requires_auth(client):
    response = client.patch("/packages/some-id", json={"status": "paused"})
    assert response.status_code == 401
