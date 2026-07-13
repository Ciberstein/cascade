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


@pytest.mark.asyncio
async def test_get_or_create_settings_recovers_from_concurrent_insert(db_engine):
    """Two near-simultaneous first-requests both SELECT and find no settings
    row, then both try to INSERT id=1. The primary-key constraint makes the
    second commit raise IntegrityError; _get_or_create_settings must catch
    it, roll back, and re-SELECT the row the other request created instead
    of letting the error surface as a 500.

    This is simulated deterministically (no real thread/asyncio race timing)
    by monkeypatching the session's commit: the first time it's called, a
    *separate* session inserts and commits the conflicting settings row
    first, then the real commit proceeds and hits the PK constraint.
    """
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        original_commit = session.commit
        commit_calls = 0

        async def racy_commit():
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 1:
                # Simulate a concurrent request winning the race: it already
                # inserted+committed the settings row via its own session,
                # in between our SELECT (which found nothing) and our
                # INSERT/COMMIT.
                async with factory() as other_session:
                    other_session.add(GlobalSettings(id=1))
                    await other_session.commit()
            await original_commit()

        session.commit = racy_commit

        row = await _get_or_create_settings(session)

        assert row.id == 1
        assert commit_calls == 1

    # Only one settings row should exist even though two inserts were attempted.
    async with factory() as verify_session:
        result = await verify_session.execute(select(GlobalSettings).where(GlobalSettings.id == 1))
        rows = result.scalars().all()
        assert len(rows) == 1
