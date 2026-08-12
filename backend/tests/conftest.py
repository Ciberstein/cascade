import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://cascade:cascade@localhost:5432/cascade_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "hunter2")
# Tests drive the scheduler directly (tests/test_scheduler.py) against a
# sqlite session; the background loop would only poll the unreachable
# DATABASE_URL above every 2s for the length of the run.
os.environ.setdefault("SCHEDULER_ENABLED", "false")

#: Token de dueño de los tests. 32 caracteres alfanuméricos, como exige
#: app.owner: sin login, ese token es la identidad.
TEST_OWNER = "testowner0000000000000000000000a"

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models import Base


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def client(db_engine):
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app, headers={"X-Cascade-Owner": TEST_OWNER}) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(client):
    """Alias histórico: ya no hay login, el cliente ya trae su dueño."""
    return client


from tests.fixtures.test_server import FlakyTestServer


@pytest_asyncio.fixture
async def test_server():
    servers: list[FlakyTestServer] = []

    async def _make(
        payload: bytes,
        support_range: bool = True,
        fail_first_n: int = 0,
        ignore_range: bool = False,
        head_status: int = 200,
        omit_content_length: bool = False,
        stream_delay_seconds: float = 0.0,
    ):
        server = FlakyTestServer(
            payload,
            support_range=support_range,
            fail_first_n=fail_first_n,
            ignore_range=ignore_range,
            head_status=head_status,
            omit_content_length=omit_content_length,
            stream_delay_seconds=stream_delay_seconds,
        )
        url = await server.start()
        servers.append(server)
        return server, url

    yield _make

    for server in servers:
        await server.stop()


@pytest_asyncio.fixture
async def session(db_engine):
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s


import httpx


@pytest_asyncio.fixture
async def async_client(db_engine):
    """Cliente HTTP sobre la app, usable desde un test async.

    ASGITransport no corre el lifespan, así que ni el scheduler ni el loop de
    crawl arrancan durante estos tests.
    """
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Cascade-Owner": TEST_OWNER},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def async_auth_client(async_client):
    """Alias histórico: ya no hay login."""
    return async_client
