import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from tests.conftest import TEST_OWNER
from app.models import Base, Chunk, DownloadItem, Package


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_package_with_items_and_chunks(session):
    package = Package(name="Test pkg", status="queued", target_dir="/downloads/test-pkg", owner_id=TEST_OWNER)
    session.add(package)
    await session.flush()

    item = DownloadItem(
        package_id=package.id,
        url="https://example.com/file.zip",
        filename="file.zip",
        status="queued",
    )
    session.add(item)
    await session.flush()

    chunk = Chunk(download_item_id=item.id, range_start=0, range_end=999, status="pending")
    session.add(chunk)
    await session.commit()

    assert package.id is not None
    assert item.package_id == package.id
    assert chunk.download_item_id == item.id
