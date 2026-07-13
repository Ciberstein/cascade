import pytest


@pytest.mark.asyncio
async def test_login_success(client):
    # ADMIN_USERNAME/ADMIN_PASSWORD are the fixed test values set at the top of conftest.py
    response = client.post("/auth/login", json={"username": "admin", "password": "hunter2"})

    assert response.status_code == 200
    assert "access_token" in response.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    response = client.post("/auth/login", json={"username": "admin", "password": "wrong"})

    assert response.status_code == 401
