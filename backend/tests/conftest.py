import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://cascade:cascade@localhost:5432/cascade_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "hunter2")

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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(client):
    client.post("/auth/login", json={"username": "admin", "password": "hunter2"})
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
    ):
        server = FlakyTestServer(
            payload,
            support_range=support_range,
            fail_first_n=fail_first_n,
            ignore_range=ignore_range,
        )
        url = await server.start()
        servers.append(server)
        return server, url

    yield _make

    for server in servers:
        await server.stop()
