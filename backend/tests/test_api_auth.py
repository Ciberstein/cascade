import datetime as dt

import pytest
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.api.auth import _get_or_create_admin
from app.auth.security import ALGORITHM, hash_password
from app.config import Settings
from app.models import User


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


@pytest.mark.asyncio
async def test_login_sets_cookie_with_matching_max_age(client):
    response = client.post("/auth/login", json={"username": "admin", "password": "hunter2"})

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    expected_max_age = Settings().jwt_expire_minutes * 60
    assert f"Max-Age={expected_max_age}" in set_cookie


@pytest.mark.asyncio
async def test_get_or_create_admin_recovers_from_concurrent_insert(db_engine):
    """Two near-simultaneous first-logins both SELECT and find no admin user,
    then both try to INSERT. The DB-level UniqueConstraint on username makes
    the second commit raise IntegrityError; _get_or_create_admin must catch
    it, roll back, and re-SELECT the row the other request created instead
    of letting the error surface as a 500.

    This is simulated deterministically (no real thread/asyncio race timing)
    by monkeypatching the session's commit: the first time it's called, a
    *separate* session inserts and commits the conflicting admin row first,
    then the real commit proceeds and hits the UniqueConstraint.
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
                # inserted+committed the admin user via its own session,
                # in between our SELECT (which found nothing) and our
                # INSERT/COMMIT.
                async with factory() as other_session:
                    other_session.add(
                        User(username="admin", password_hash=hash_password("hunter2"))
                    )
                    await other_session.commit()
            await original_commit()

        session.commit = racy_commit

        user = await _get_or_create_admin(session)

        assert user.username == "admin"
        assert commit_calls == 1

    # Only one admin row should exist even though two inserts were attempted.
    async with factory() as verify_session:
        result = await verify_session.execute(select(User).where(User.username == "admin"))
        users = result.scalars().all()
        assert len(users) == 1


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    response = client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_user_when_authenticated(client):
    client.post("/auth/login", json={"username": "admin", "password": "hunter2"})
    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["username"] == "admin"


@pytest.mark.asyncio
async def test_me_rejects_garbage_cookie(client):
    client.cookies.set("access_token", "not-a-valid-jwt")
    response = client.get("/auth/me")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_token_missing_sub_claim(client):
    # A validly-signed token that simply has no "sub" claim must not crash
    # get_current_user with an uncaught KeyError -- it should 401 cleanly.
    settings = Settings()
    expire = dt.datetime.utcnow() + dt.timedelta(minutes=settings.jwt_expire_minutes)
    token = jwt.encode({"exp": expire}, settings.jwt_secret, algorithm=ALGORITHM)

    client.cookies.set("access_token", token)
    response = client.get("/auth/me")

    assert response.status_code == 401
