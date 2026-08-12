import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.api.settings import _get_or_create_settings
from app.models import GlobalSettings


@pytest.mark.asyncio
async def test_get_settings_returns_defaults(auth_client):
    response = auth_client.get("/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["max_concurrent_downloads"] == 3
    assert body["chunks_per_file"] == 4
    assert body["max_speed_kbps"] == 0
    assert body["max_concurrent_crawls"] == 5


@pytest.mark.asyncio
async def test_settings_still_require_an_owner_token(client):
    client.headers.pop("X-Cascade-Owner", None)

    # Sigue sin haber login, pero la configuración no queda accesible sin
    # identificarse siquiera como navegador.
    assert client.get("/settings").status_code == 400

