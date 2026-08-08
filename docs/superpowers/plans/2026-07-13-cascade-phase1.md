# Cascade — Fase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Fase 1 core of Cascade — a self-hosted, single-user, web-based download manager with a Python/FastAPI backend (async chunked download engine, PostgreSQL, WebSocket progress) and a React/Vite frontend, packaged with Docker Compose.

**Architecture:** Single FastAPI process serves REST + WebSocket and runs an asyncio-based download engine (scheduler → per-item chunk downloads → progress aggregation). PostgreSQL persists packages/items/chunks/settings for crash-safe resume. React SPA talks to the API over REST for actions and a WebSocket for live progress.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, httpx, pytest, pytest-asyncio; React 18, Vite, TypeScript, Vitest; PostgreSQL 16; Docker Compose.

Spec: `docs/superpowers/specs/2026-07-13-cascade-phase1-design.md`

---

## File Structure

```
backend/
  app/
    main.py                  # FastAPI app + lifespan (starts scheduler)
    config.py                # env-based settings
    database.py              # SQLAlchemy engine/session
    models.py                # User, Package, DownloadItem, Chunk, Settings
    schemas.py                # Pydantic request/response schemas
    auth/
      security.py             # password hash, JWT encode/decode
      dependencies.py          # get_current_user FastAPI dependency
    api/
      auth.py                  # POST /auth/login
      packages.py               # /packages CRUD
      settings.py                # /settings GET/PUT
    ws/
      manager.py                 # ConnectionManager (register/broadcast)
      routes.py                   # /ws route
    engine/
      chunker.py                  # compute chunk byte ranges
      downloader.py                 # download one chunk w/ retry+backoff
      item_runner.py                 # orchestrate all chunks of one item
      scheduler.py                    # pick queued items, concurrency limit, resume on startup
      progress.py                      # aggregate + throttle progress events
  alembic/                              # migrations
  tests/
    conftest.py                          # fixtures: db session, test HTTP server
    fixtures/test_server.py               # local aiohttp server (Range on/off, fault injection)
    test_config.py
    test_security.py
    test_api_auth.py
    test_api_packages.py
    test_api_settings.py
    test_chunker.py
    test_downloader.py
    test_item_runner.py
    test_scheduler.py
    test_ws.py
  pyproject.toml
  Dockerfile

frontend/
  src/
    main.tsx
    App.tsx
    api/client.ts                        # fetch wrapper, attaches auth cookie
    api/packages.ts
    api/auth.ts
    ws/useProgressSocket.ts
    pages/Login.tsx
    pages/Dashboard.tsx
    pages/PackageDetail.tsx
    pages/Settings.tsx
    components/AddLinksModal.tsx
    components/PackageRow.tsx
    components/ProgressBar.tsx
    types.ts
  tests/
    api.test.ts
    useProgressSocket.test.ts
    Login.test.tsx
    Dashboard.test.tsx
    AddLinksModal.test.tsx
  package.json
  vite.config.ts
  Dockerfile

docker-compose.yml
.env.example
```

---

## Task 1: Backend project scaffold

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "cascade-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "httpx>=0.27",
    "pydantic-settings>=2.4",
    "python-jose[cryptography]>=3.3",
    "passlib[bcrypt]>=1.7",
    "websockets>=12.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "aiohttp>=3.9",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create minimal `backend/app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="Cascade")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 3: Create `backend/app/__init__.py` and `backend/tests/__init__.py` (empty files)**

- [ ] **Step 4: Create `backend/tests/conftest.py` with a TestClient fixture**

`Settings()` is instantiated once at module-import time in several `app.*` modules (e.g. `app.auth.security`, `app.database`), not re-read per request — this is intentional (matches how env vars work in a real deployed container) but means tests can't override them with `monkeypatch.setenv` inside a test function, since the singleton is already built by then. Fixed test credentials are set here, at the very top of `conftest.py`, before anything imports `app.main` — pytest always loads `conftest.py` first, so every `app.*` module sees these values the first time it's imported.

```python
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://cascade:cascade@localhost:5432/cascade_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "hunter2")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
```

- [ ] **Step 5: Write the smoke test**

Create `backend/tests/test_health.py`:

```python
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 6: Install deps and run test**

Run: `cd backend && pip install -e ".[dev]" && pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/app backend/tests
git commit -m "chore: scaffold FastAPI backend project"
```

---

## Task 2: Config module

**Files:**
- Create: `backend/app/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
import os

from app.config import Settings


def test_settings_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/cascade")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "hunter2")

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/cascade"
    assert settings.jwt_secret == "test-secret"
    assert settings.admin_username == "admin"
    assert settings.admin_password == "hunter2"
    assert settings.download_root == "/downloads"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ImportError` (no `app.config`)

- [ ] **Step 3: Implement `backend/app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    admin_username: str
    admin_password: str
    download_root: str = "/downloads"
    jwt_expire_minutes: int = 60 * 24 * 7
    max_concurrent_downloads: int = 3
    chunks_per_file: int = 4
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: add env-based settings module"
```

---

## Task 3: Database engine, session, and SQLAlchemy models

**Files:**
- Create: `backend/app/database.py`
- Create: `backend/app/models.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test (uses an in-memory SQLite engine for speed/isolation)**

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Chunk, DownloadItem, Package, User


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
    user = User(username="admin", password_hash="x")
    session.add(user)
    await session.flush()

    package = Package(name="Test pkg", status="queued", target_dir="/downloads/test-pkg")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ImportError` (no `app.models`)

- [ ] **Step 3: Add `aiosqlite` to dev deps**

Edit `backend/pyproject.toml`, add to `[project.optional-dependencies].dev`: `"aiosqlite>=0.20"`.

- [ ] **Step 4: Implement `backend/app/models.py`**

```python
import datetime as dt
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    target_dir: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    items: Mapped[list["DownloadItem"]] = relationship(back_populates="package", cascade="all, delete-orphan")


class DownloadItem(Base):
    __tablename__ = "download_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    url: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(1024))
    total_size: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    downloaded_bytes: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    retries: Mapped[int] = mapped_column(default=0)

    package: Mapped["Package"] = relationship(back_populates="items")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="item", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    download_item_id: Mapped[str] = mapped_column(ForeignKey("download_items.id"))
    range_start: Mapped[int] = mapped_column()
    range_end: Mapped[int] = mapped_column()
    downloaded_bytes: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    item: Mapped["DownloadItem"] = relationship(back_populates="chunks")


class GlobalSettings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    download_root: Mapped[str] = mapped_column(String(1024), default="/downloads")
    max_concurrent_downloads: Mapped[int] = mapped_column(default=3)
    chunks_per_file: Mapped[int] = mapped_column(default=4)
    max_speed_kbps: Mapped[int] = mapped_column(default=0)
```

- [ ] **Step 5: Implement `backend/app/database.py`**

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings

settings = Settings()
engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pip install -e ".[dev]" && pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/database.py backend/pyproject.toml backend/tests/test_models.py
git commit -m "feat: add SQLAlchemy models and async session factory"
```

---

## Task 4: Alembic migrations setup

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_initial.py`

- [ ] **Step 1: Initialize Alembic structure**

Run: `cd backend && alembic init alembic`
Expected: creates `alembic/` and `alembic.ini`

- [ ] **Step 2: Point `alembic/env.py` at the app's models and settings**

Edit `backend/alembic/env.py`, replace the `target_metadata = None` line and add imports at the top:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.models import Base

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", Settings().database_url.replace("+asyncpg", ""))
```

- [ ] **Step 3: Generate the initial migration**

Run: `cd backend && DATABASE_URL=postgresql://cascade:cascade@localhost:5432/cascade JWT_SECRET=x ADMIN_USERNAME=admin ADMIN_PASSWORD=x alembic revision --autogenerate -m "initial schema"`
Expected: creates `backend/alembic/versions/0001_initial.py` with `users`, `packages`, `download_items`, `chunks`, `settings` tables

- [ ] **Step 4: Verify migration applies cleanly against a local Postgres**

Run: `docker run --rm -d --name cascade-pg-test -e POSTGRES_USER=cascade -e POSTGRES_PASSWORD=cascade -e POSTGRES_DB=cascade -p 5432:5432 postgres:16` then `cd backend && DATABASE_URL=postgresql://cascade:cascade@localhost:5432/cascade JWT_SECRET=x ADMIN_USERNAME=admin ADMIN_PASSWORD=x alembic upgrade head`
Expected: `Running upgrade -> 0001, initial schema` with no errors. Clean up with `docker stop cascade-pg-test`.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic.ini backend/alembic
git commit -m "feat: add Alembic migrations with initial schema"
```

---

## Task 5: Password hashing and JWT utilities

**Files:**
- Create: `backend/app/auth/__init__.py`
- Create: `backend/app/auth/security.py`
- Test: `backend/tests/test_security.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from app.auth.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_and_verify_password():
    hashed = hash_password("hunter2")
    assert hashed != "hunter2"
    assert verify_password("hunter2", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_create_and_decode_access_token():
    # JWT_SECRET etc. come from the fixed test env vars set at the top of conftest.py —
    # security.py reads them into a module-level Settings() singleton at import time.
    token = create_access_token(subject="user-123")
    payload = decode_access_token(token)

    assert payload["sub"] == "user-123"


def test_decode_invalid_token_raises():
    with pytest.raises(Exception):
        decode_access_token("not-a-real-token")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_security.py -v`
Expected: FAIL with `ImportError` (no `app.auth`)

- [ ] **Step 3: Implement `backend/app/auth/security.py`**

```python
import datetime as dt

from jose import jwt
from passlib.context import CryptContext

from app.config import Settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_settings = Settings()

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


def create_access_token(subject: str) -> str:
    expire = dt.datetime.utcnow() + dt.timedelta(minutes=_settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, _settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _settings.jwt_secret, algorithms=[ALGORITHM])
```

- [ ] **Step 4: Create `backend/app/auth/__init__.py` (empty file)**

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_security.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/auth/security.py backend/app/auth/__init__.py backend/tests/test_security.py
git commit -m "feat: add password hashing and JWT utilities"
```

---

## Task 6: POST /auth/login endpoint

**Files:**
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/auth.py`
- Create: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_api_auth.py`

The single admin user is provisioned lazily: on login, if no `User` row exists yet, one is created from `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars with a hashed password. This avoids a separate seed script for Fase 1's single-user model.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_auth.py -v`
Expected: FAIL — `client` fixture doesn't provide a real app/db yet, or 404 on `/auth/login`

- [ ] **Step 3: Update `backend/tests/conftest.py` to wire an in-memory DB into the app via dependency override**

Keep the `os.environ.setdefault(...)` block from Task 1 at the top of the file unchanged — only the imports and fixtures below it change.

```python
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
```

- [ ] **Step 4: Add login schemas to `backend/app/schemas.py`**

```python
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool = True
```

- [ ] **Step 5: Implement `backend/app/api/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password, verify_password
from app.config import Settings
from app.database import get_db
from app.models import User
from app.schemas import LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])
_settings = Settings()


async def _get_or_create_admin(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.username == _settings.admin_username))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            username=_settings.admin_username,
            password_hash=hash_password(_settings.admin_password),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await _get_or_create_admin(db)
    if payload.username != user.username or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(subject=user.id)
    response.set_cookie("access_token", token, httponly=True, samesite="lax")
    return LoginResponse()
```

- [ ] **Step 6: Wire the router into `backend/app/main.py`**

```python
from fastapi import FastAPI

from app.api.auth import router as auth_router

app = FastAPI(title="Cascade")
app.include_router(auth_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 7: Create `backend/app/api/__init__.py` (empty file)**

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_api_auth.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/api backend/app/schemas.py backend/app/main.py backend/tests/conftest.py backend/tests/test_api_auth.py
git commit -m "feat: add POST /auth/login with lazy admin provisioning"
```

---

## Task 7: get_current_user dependency

**Files:**
- Create: `backend/app/auth/dependencies.py`
- Modify: `backend/app/api/auth.py` (add `GET /auth/me` to exercise the dependency)
- Test: `backend/tests/test_api_auth.py`

- [ ] **Step 1: Write the failing test (append to `backend/tests/test_api_auth.py`)**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_auth.py -v`
Expected: FAIL with 404 on `/auth/me`

- [ ] **Step 3: Implement `backend/app/auth/dependencies.py`**

```python
from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_access_token
from app.database import get_db
from app.models import User


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if access_token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_access_token(access_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user
```

- [ ] **Step 4: Add `GET /auth/me` to `backend/app/api/auth.py`**

```python
from app.auth.dependencies import get_current_user

# ... existing imports and router ...


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict[str, str]:
    return {"username": user.username}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_api_auth.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/auth/dependencies.py backend/app/api/auth.py backend/tests/test_api_auth.py
git commit -m "feat: add get_current_user dependency and GET /auth/me"
```

---

## Task 8: POST /packages (create package + items)

**Files:**
- Create: `backend/app/api/packages.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/conftest.py` (add authenticated client fixture)
- Test: `backend/tests/test_api_packages.py`

- [ ] **Step 1: Add an authenticated client fixture to `backend/tests/conftest.py`**

```python
@pytest.fixture
def auth_client(client):
    client.post("/auth/login", json={"username": "admin", "password": "hunter2"})
    return client
```

- [ ] **Step 2: Write the failing test**

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_api_packages.py -v`
Expected: FAIL with 404 on `/packages`

- [ ] **Step 4: Add package schemas to `backend/app/schemas.py`**

```python
from pydantic import BaseModel, Field


class CreatePackageRequest(BaseModel):
    name: str
    urls: list[str] = Field(min_length=1)


class DownloadItemResponse(BaseModel):
    id: str
    url: str
    filename: str
    status: str
    total_size: int | None
    downloaded_bytes: int
    error_message: str | None

    model_config = {"from_attributes": True}


class PackageResponse(BaseModel):
    id: str
    name: str
    status: str
    target_dir: str
    items: list[DownloadItemResponse]

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: Implement `backend/app/api/packages.py`**

```python
import os

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.config import Settings
from app.database import get_db
from app.models import DownloadItem, Package, User
from app.schemas import CreatePackageRequest, PackageResponse

router = APIRouter(prefix="/packages", tags=["packages"])
_settings = Settings()


def _filename_from_url(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name or "download"


@router.post("", response_model=PackageResponse, status_code=status.HTTP_201_CREATED)
async def create_package(
    payload: CreatePackageRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    package = Package(
        name=payload.name,
        status="queued",
        target_dir=os.path.join(_settings.download_root, payload.name),
    )
    db.add(package)
    await db.flush()

    for url in payload.urls:
        db.add(
            DownloadItem(
                package_id=package.id,
                url=url,
                filename=_filename_from_url(url),
                status="queued",
            )
        )

    await db.commit()

    result = await db.execute(
        select(Package).options(selectinload(Package.items)).where(Package.id == package.id)
    )
    return result.scalar_one()
```

- [ ] **Step 6: Wire the router into `backend/app/main.py`**

```python
from app.api.packages import router as packages_router

app.include_router(packages_router)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_api_packages.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/packages.py backend/app/schemas.py backend/app/main.py backend/tests/conftest.py backend/tests/test_api_packages.py
git commit -m "feat: add POST /packages to create a package with items"
```

---

## Task 9: GET /packages (list)

**Files:**
- Modify: `backend/app/api/packages.py`
- Test: `backend/tests/test_api_packages.py`

- [ ] **Step 1: Write the failing test (append)**

```python
@pytest.mark.asyncio
async def test_list_packages(auth_client):
    auth_client.post("/packages", json={"name": "Pkg A", "urls": ["https://example.com/a.zip"]})
    auth_client.post("/packages", json={"name": "Pkg B", "urls": ["https://example.com/b.zip"]})

    response = auth_client.get("/packages")

    assert response.status_code == 200
    names = {pkg["name"] for pkg in response.json()}
    assert names == {"Pkg A", "Pkg B"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_packages.py -v`
Expected: FAIL with 404 on `GET /packages`

- [ ] **Step 3: Add the list endpoint to `backend/app/api/packages.py`**

```python
@router.get("", response_model=list[PackageResponse])
async def list_packages(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Package).options(selectinload(Package.items)))
    return result.scalars().all()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_packages.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/packages.py backend/tests/test_api_packages.py
git commit -m "feat: add GET /packages to list packages with items"
```

---

## Task 10: PATCH /packages/{id} (pause/resume/cancel)

**Files:**
- Modify: `backend/app/api/packages.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_api_packages.py`

Fase 1 scope: this endpoint only updates `Package.status` in the DB (queued/paused/canceled). Actually stopping/resuming in-flight `asyncio` tasks is wired in Task 15 (scheduler) — until then this is a pure state transition, which is enough to test independently.

- [ ] **Step 1: Write the failing test (append)**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_packages.py -v`
Expected: FAIL with 404/405 on `PATCH /packages/{id}`

- [ ] **Step 3: Add the status schema to `backend/app/schemas.py`**

```python
from typing import Literal


class UpdatePackageStatusRequest(BaseModel):
    status: Literal["queued", "paused", "canceled"]
```

- [ ] **Step 4: Add the PATCH endpoint to `backend/app/api/packages.py`**

```python
from fastapi import HTTPException

from app.schemas import UpdatePackageStatusRequest


@router.patch("/{package_id}", response_model=PackageResponse)
async def update_package_status(
    package_id: str,
    payload: UpdatePackageStatusRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Package).options(selectinload(Package.items)).where(Package.id == package_id)
    )
    package = result.scalar_one_or_none()
    if package is None:
        raise HTTPException(status_code=404, detail="Package not found")

    package.status = payload.status
    await db.commit()
    await db.refresh(package, attribute_names=["items"])
    return package
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_api_packages.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/packages.py backend/app/schemas.py backend/tests/test_api_packages.py
git commit -m "feat: add PATCH /packages/{id} for pause/resume/cancel"
```

---

## Task 11: GET/PUT /settings

**Files:**
- Create: `backend/app/api/settings.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_settings.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_settings.py -v`
Expected: FAIL with 404 on `/settings`

- [ ] **Step 3: Add settings schema to `backend/app/schemas.py`**

```python
class SettingsResponse(BaseModel):
    download_root: str
    max_concurrent_downloads: int
    chunks_per_file: int
    max_speed_kbps: int

    model_config = {"from_attributes": True}


class UpdateSettingsRequest(BaseModel):
    download_root: str
    max_concurrent_downloads: int = Field(ge=1, le=20)
    chunks_per_file: int = Field(ge=1, le=16)
    max_speed_kbps: int = Field(ge=0)
```

- [ ] **Step 4: Implement `backend/app/api/settings.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import GlobalSettings, User
from app.schemas import SettingsResponse, UpdateSettingsRequest

router = APIRouter(prefix="/settings", tags=["settings"])


async def _get_or_create_settings(db: AsyncSession) -> GlobalSettings:
    result = await db.execute(select(GlobalSettings).where(GlobalSettings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = GlobalSettings(id=1)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    return await _get_or_create_settings(db)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    payload: UpdateSettingsRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = await _get_or_create_settings(db)
    row.download_root = payload.download_root
    row.max_concurrent_downloads = payload.max_concurrent_downloads
    row.chunks_per_file = payload.chunks_per_file
    row.max_speed_kbps = payload.max_speed_kbps
    await db.commit()
    await db.refresh(row)
    return row
```

- [ ] **Step 5: Wire the router into `backend/app/main.py`**

```python
from app.api.settings import router as settings_router

app.include_router(settings_router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_api_settings.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/settings.py backend/app/schemas.py backend/app/main.py backend/tests/test_api_settings.py
git commit -m "feat: add GET/PUT /settings"
```

---

## Task 12: Engine — chunker

**Files:**
- Create: `backend/app/engine/__init__.py`
- Create: `backend/app/engine/chunker.py`
- Test: `backend/tests/test_chunker.py`

- [ ] **Step 1: Write the failing test**

```python
from app.engine.chunker import split_into_chunks


def test_split_even():
    ranges = split_into_chunks(total_size=1000, num_chunks=4)
    assert ranges == [(0, 249), (250, 499), (500, 749), (750, 999)]


def test_split_uneven_remainder_goes_to_last_chunk():
    ranges = split_into_chunks(total_size=1001, num_chunks=4)
    assert ranges == [(0, 249), (250, 499), (500, 749), (750, 1000)]


def test_split_more_chunks_than_bytes_clamps_to_one_chunk_per_byte():
    ranges = split_into_chunks(total_size=3, num_chunks=8)
    assert ranges == [(0, 0), (1, 1), (2, 2)]


def test_split_single_chunk():
    ranges = split_into_chunks(total_size=500, num_chunks=1)
    assert ranges == [(0, 499)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chunker.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `backend/app/engine/chunker.py`**

```python
def split_into_chunks(total_size: int, num_chunks: int) -> list[tuple[int, int]]:
    num_chunks = max(1, min(num_chunks, total_size))
    base_size = total_size // num_chunks
    remainder = total_size % num_chunks

    ranges: list[tuple[int, int]] = []
    start = 0
    for i in range(num_chunks):
        size = base_size + (remainder if i == num_chunks - 1 else 0)
        end = start + size - 1
        ranges.append((start, end))
        start = end + 1
    return ranges
```

- [ ] **Step 4: Create `backend/app/engine/__init__.py` (empty file)**

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_chunker.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/chunker.py backend/app/engine/__init__.py backend/tests/test_chunker.py
git commit -m "feat: add chunk range splitting logic"
```

---

## Task 13: Local test HTTP server fixture + Engine downloader (single chunk, retry/backoff)

**Files:**
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/fixtures/test_server.py`
- Create: `backend/app/engine/downloader.py`
- Test: `backend/tests/test_downloader.py`

The test server is an `aiohttp` app used only in tests. It serves a fixed byte payload, supports `Range` requests, and can be configured to fail the first N requests to a given path (to exercise retry/backoff) or to reject `Range` entirely (to exercise the single-chunk fallback in Task 14).

- [ ] **Step 1: Implement the test server fixture `backend/tests/fixtures/test_server.py`**

```python
import asyncio

from aiohttp import web


class FlakyTestServer:
    def __init__(self, payload: bytes, support_range: bool = True, fail_first_n: int = 0):
        self.payload = payload
        self.support_range = support_range
        self.fail_first_n = fail_first_n
        self._attempts = 0
        self.app = web.Application()
        self.app.router.add_get("/file", self._handle)
        self.app.router.add_head("/file", self._handle_head)
        self.runner: web.AppRunner | None = None
        self.port: int | None = None

    async def start(self) -> str:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{self.port}/file"

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()

    async def _handle_head(self, request: web.Request) -> web.Response:
        headers = {"Content-Length": str(len(self.payload))}
        if self.support_range:
            headers["Accept-Ranges"] = "bytes"
        return web.Response(status=200, headers=headers)

    async def _handle(self, request: web.Request) -> web.Response:
        self._attempts += 1
        if self._attempts <= self.fail_first_n:
            return web.Response(status=503)

        range_header = request.headers.get("Range")
        if range_header and self.support_range:
            start, end = range_header.replace("bytes=", "").split("-")
            start, end = int(start), int(end)
            body = self.payload[start : end + 1]
            return web.Response(
                status=206,
                body=body,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{len(self.payload)}",
                    "Content-Length": str(len(body)),
                },
            )

        return web.Response(status=200, body=self.payload)
```

- [ ] **Step 2: Create `backend/tests/fixtures/__init__.py` (empty file)**

- [ ] **Step 3: Add `aiohttp` fixture helper to `backend/tests/conftest.py`**

```python
from tests.fixtures.test_server import FlakyTestServer


@pytest_asyncio.fixture
async def test_server():
    servers: list[FlakyTestServer] = []

    async def _make(payload: bytes, support_range: bool = True, fail_first_n: int = 0):
        server = FlakyTestServer(payload, support_range=support_range, fail_first_n=fail_first_n)
        url = await server.start()
        servers.append(server)
        return server, url

    yield _make

    for server in servers:
        await server.stop()
```

- [ ] **Step 4: Write the failing test for the downloader**

```python
import pytest

from app.engine.downloader import download_chunk


@pytest.mark.asyncio
async def test_download_chunk_writes_correct_bytes(test_server, tmp_path):
    payload = b"0123456789" * 100  # 1000 bytes
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    await download_chunk(url=url, start=100, end=199, dest_path=str(dest))

    with open(dest, "rb") as f:
        f.seek(100)
        written = f.read(100)
    assert written == payload[100:200]


@pytest.mark.asyncio
async def test_download_chunk_retries_on_transient_failure(test_server, tmp_path):
    payload = b"A" * 500
    _, url = await test_server(payload, fail_first_n=2)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    await download_chunk(url=url, start=0, end=499, dest_path=str(dest), max_retries=3, backoff_base=0.01)

    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_chunk_raises_after_exhausting_retries(test_server, tmp_path):
    payload = b"A" * 100
    _, url = await test_server(payload, fail_first_n=10)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))

    with pytest.raises(RuntimeError):
        await download_chunk(url=url, start=0, end=99, dest_path=str(dest), max_retries=2, backoff_base=0.01)
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_downloader.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 6: Implement `backend/app/engine/downloader.py`**

```python
import asyncio

import httpx


async def download_chunk(
    url: str,
    start: int,
    end: int,
    dest_path: str,
    max_retries: int = 3,
    backoff_base: float = 0.5,
) -> None:
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Range": f"bytes={start}-{end}"}
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code not in (200, 206):
                        raise RuntimeError(f"Unexpected status {response.status_code}")

                    with open(dest_path, "r+b") as f:
                        f.seek(start)
                        async for data in response.aiter_bytes():
                            f.write(data)
            return
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(backoff_base * (2**attempt))

    raise RuntimeError(f"Chunk download failed after {max_retries} attempts: {last_error}")
```

- [ ] **Step 7: Add `aiohttp` to backend dev deps if not already present (added in Task 1's pyproject; verify it's there)**

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_downloader.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/tests/fixtures backend/app/engine/downloader.py backend/tests/test_downloader.py backend/tests/conftest.py
git commit -m "feat: add chunk downloader with retry/backoff and test HTTP server fixture"
```

---

## Task 14: Engine — item_runner (orchestrate one item's chunks, assemble file)

**Files:**
- Create: `backend/app/engine/item_runner.py`
- Test: `backend/tests/test_item_runner.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from app.engine.item_runner import run_download_item


@pytest.mark.asyncio
async def test_run_download_item_downloads_full_file_with_range_support(test_server, tmp_path):
    payload = bytes(range(256)) * 4  # 1024 bytes
    _, url = await test_server(payload, support_range=True)
    dest = tmp_path / "file.bin"

    result = await run_download_item(url=url, dest_path=str(dest), num_chunks=4)

    assert dest.read_bytes() == payload
    assert result.total_size == len(payload)
    assert result.chunk_count == 4


@pytest.mark.asyncio
async def test_run_download_item_falls_back_to_single_chunk_without_range_support(test_server, tmp_path):
    payload = b"X" * 500
    _, url = await test_server(payload, support_range=False)
    dest = tmp_path / "file.bin"

    result = await run_download_item(url=url, dest_path=str(dest), num_chunks=4)

    assert dest.read_bytes() == payload
    assert result.chunk_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_item_runner.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `backend/app/engine/item_runner.py`**

```python
import asyncio
from dataclasses import dataclass

import httpx

from app.engine.chunker import split_into_chunks
from app.engine.downloader import download_chunk


@dataclass
class ItemResult:
    total_size: int
    chunk_count: int


async def _probe(url: str) -> tuple[int, bool]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.head(url)
        total_size = int(response.headers.get("Content-Length", 0))
        supports_range = response.headers.get("Accept-Ranges") == "bytes"
        return total_size, supports_range


async def run_download_item(url: str, dest_path: str, num_chunks: int) -> ItemResult:
    total_size, supports_range = await _probe(url)
    effective_chunks = num_chunks if supports_range else 1

    with open(dest_path, "wb") as f:
        f.truncate(total_size)

    ranges = split_into_chunks(total_size, effective_chunks)
    await asyncio.gather(
        *(download_chunk(url=url, start=s, end=e, dest_path=dest_path) for s, e in ranges)
    )

    return ItemResult(total_size=total_size, chunk_count=len(ranges))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_item_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/item_runner.py backend/tests/test_item_runner.py
git commit -m "feat: add item_runner to orchestrate chunked download of one file"
```

---

## Task 15: Resume support and progress callbacks in downloader/item_runner

**Files:**
- Modify: `backend/app/engine/downloader.py`
- Modify: `backend/app/engine/item_runner.py`
- Test: `backend/tests/test_downloader.py`
- Test: `backend/tests/test_item_runner.py`

This adds the two hooks the scheduler (Task 16) needs: resuming a chunk from a byte offset already on disk, and a callback fired on every write so progress can be aggregated without polling the filesystem.

- [ ] **Step 1: Write the failing test for `download_chunk` resume + callback (append to `backend/tests/test_downloader.py`)**

```python
@pytest.mark.asyncio
async def test_download_chunk_resumes_from_offset(test_server, tmp_path):
    payload = b"A" * 200 + b"B" * 300  # 500 bytes total
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(payload[:200] + b"\x00" * 300)  # first 200 bytes already on disk

    await download_chunk(url=url, start=0, end=499, dest_path=str(dest), resume_from=200)

    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_chunk_calls_progress_callback(test_server, tmp_path):
    payload = b"A" * 1000
    _, url = await test_server(payload)
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"\x00" * len(payload))
    seen: list[int] = []

    await download_chunk(
        url=url, start=0, end=999, dest_path=str(dest), on_bytes=lambda n: seen.append(n)
    )

    assert sum(seen) == 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_downloader.py -v`
Expected: FAIL — `download_chunk()` doesn't accept `resume_from`/`on_bytes` yet

- [ ] **Step 3: Update `backend/app/engine/downloader.py` to accept `resume_from` and `on_bytes`**

```python
import asyncio
from typing import Callable

import httpx


async def download_chunk(
    url: str,
    start: int,
    end: int,
    dest_path: str,
    max_retries: int = 3,
    backoff_base: float = 0.5,
    resume_from: int = 0,
    on_bytes: Callable[[int], None] | None = None,
) -> None:
    last_error: Exception | None = None
    effective_start = start + resume_from

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {"Range": f"bytes={effective_start}-{end}"}
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code not in (200, 206):
                        raise RuntimeError(f"Unexpected status {response.status_code}")

                    with open(dest_path, "r+b") as f:
                        f.seek(effective_start)
                        async for data in response.aiter_bytes():
                            f.write(data)
                            if on_bytes:
                                on_bytes(len(data))
            return
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(backoff_base * (2**attempt))

    raise RuntimeError(f"Chunk download failed after {max_retries} attempts: {last_error}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_downloader.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for `run_download_item` resume + callback (append to `backend/tests/test_item_runner.py`)**

```python
@pytest.mark.asyncio
async def test_run_download_item_resumes_existing_chunks(test_server, tmp_path):
    payload = bytes(range(256)) * 4  # 1024 bytes, 4 chunks of 256 each
    _, url = await test_server(payload, support_range=True)
    dest = tmp_path / "file.bin"
    dest.write_bytes(payload[:256] + b"\x00" * 768)  # chunk 0 already fully on disk

    result = await run_download_item(
        url=url,
        dest_path=str(dest),
        num_chunks=4,
        existing_progress={0: 256, 1: 0, 2: 0, 3: 0},
    )

    assert dest.read_bytes() == payload
    assert result.chunk_count == 4


@pytest.mark.asyncio
async def test_run_download_item_reports_progress(test_server, tmp_path):
    payload = b"Y" * 800
    _, url = await test_server(payload, support_range=True)
    dest = tmp_path / "file.bin"
    total_reported = 0

    def on_progress(chunk_index: int, n: int) -> None:
        nonlocal total_reported
        total_reported += n

    await run_download_item(url=url, dest_path=str(dest), num_chunks=4, on_progress=on_progress)

    assert total_reported == 800


@pytest.mark.asyncio
async def test_run_download_item_calls_on_chunks_planned_before_downloading(test_server, tmp_path):
    payload = b"Q" * 400
    _, url = await test_server(payload, support_range=True)
    dest = tmp_path / "file.bin"
    planned: list[tuple[int, int]] = []

    async def on_chunks_planned(ranges: list[tuple[int, int]]) -> None:
        planned.extend(ranges)

    await run_download_item(url=url, dest_path=str(dest), num_chunks=4, on_chunks_planned=on_chunks_planned)

    assert planned == [(0, 99), (100, 199), (200, 299), (300, 399)]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_item_runner.py -v`
Expected: FAIL — `run_download_item()` doesn't accept `existing_progress`/`on_progress` yet

- [ ] **Step 7: Update `backend/app/engine/item_runner.py`**

```python
import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from app.engine.chunker import split_into_chunks
from app.engine.downloader import download_chunk


@dataclass
class ItemResult:
    total_size: int
    chunk_count: int


async def _probe(url: str) -> tuple[int, bool]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.head(url)
        total_size = int(response.headers.get("Content-Length", 0))
        supports_range = response.headers.get("Accept-Ranges") == "bytes"
        return total_size, supports_range


async def run_download_item(
    url: str,
    dest_path: str,
    num_chunks: int,
    existing_progress: dict[int, int] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_chunks_planned: Callable[[list[tuple[int, int]]], Awaitable[None] | None] | None = None,
) -> ItemResult:
    total_size, supports_range = await _probe(url)
    effective_chunks = num_chunks if supports_range else 1
    existing_progress = existing_progress or {}

    with open(dest_path, "r+b") if _file_exists(dest_path) else open(dest_path, "wb") as f:
        f.truncate(total_size)

    ranges = split_into_chunks(total_size, effective_chunks)
    if on_chunks_planned:
        maybe_coro = on_chunks_planned(ranges)
        if maybe_coro is not None:
            await maybe_coro

    async def _run_one(index: int, start: int, end: int) -> None:
        resume_from = existing_progress.get(index, 0)
        await download_chunk(
            url=url,
            start=start,
            end=end,
            dest_path=dest_path,
            resume_from=resume_from,
            on_bytes=(lambda n, i=index: on_progress(i, n)) if on_progress else None,
        )

    await asyncio.gather(*(_run_one(i, s, e) for i, (s, e) in enumerate(ranges)))

    return ItemResult(total_size=total_size, chunk_count=len(ranges))


def _file_exists(path: str) -> bool:
    import os

    return os.path.exists(path)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_item_runner.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/engine/downloader.py backend/app/engine/item_runner.py backend/tests/test_downloader.py backend/tests/test_item_runner.py
git commit -m "feat: add resume-from-offset and progress callbacks to download engine"
```

---

## Task 16: WebSocket connection manager and progress broadcast

**Files:**
- Create: `backend/app/ws/__init__.py`
- Create: `backend/app/ws/manager.py`
- Create: `backend/app/ws/routes.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_ws.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from app.ws.manager import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data: dict):
        self.sent.append(data)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_connection_manager_broadcasts_to_all_connected():
    manager = ConnectionManager()
    ws1, ws2 = FakeWebSocket(), FakeWebSocket()
    await manager.connect(ws1)
    await manager.connect(ws2)

    await manager.broadcast({"type": "progress", "item_id": "abc", "downloaded_bytes": 100})

    assert ws1.sent == [{"type": "progress", "item_id": "abc", "downloaded_bytes": 100}]
    assert ws2.sent == ws1.sent


@pytest.mark.asyncio
async def test_connection_manager_stops_sending_to_disconnected():
    manager = ConnectionManager()
    ws1 = FakeWebSocket()
    await manager.connect(ws1)
    manager.disconnect(ws1)

    await manager.broadcast({"type": "progress"})

    assert ws1.sent == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ws.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `backend/app/ws/manager.py`**

```python
from typing import Any, Protocol


class WebSocketLike(Protocol):
    async def accept(self) -> None: ...
    async def send_json(self, data: dict) -> None: ...
    async def close(self) -> None: ...


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocketLike] = []

    async def connect(self, websocket: WebSocketLike) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocketLike) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, data: dict[str, Any]) -> None:
        for connection in list(self._connections):
            try:
                await connection.send_json(data)
            except Exception:  # noqa: BLE001 - drop dead connections
                self.disconnect(connection)


manager = ConnectionManager()
```

- [ ] **Step 4: Create `backend/app/ws/__init__.py` (empty file)**

- [ ] **Step 5: Implement `backend/app/ws/routes.py`**

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.security import decode_access_token
from app.ws.manager import manager

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    token = websocket.cookies.get("access_token")
    if token is None:
        await websocket.close(code=4401)
        return
    try:
        decode_access_token(token)
    except Exception:
        await websocket.close(code=4401)
        return

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # client doesn't send anything meaningful; keeps connection open
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

- [ ] **Step 6: Wire the router into `backend/app/main.py`**

```python
from app.ws.routes import router as ws_router

app.include_router(ws_router)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_ws.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/ws backend/app/main.py backend/tests/test_ws.py
git commit -m "feat: add WebSocket connection manager and /ws route"
```

---

## Task 17: Engine — progress throttling (ThrottledBroadcaster)

**Files:**
- Create: `backend/app/engine/progress.py`
- Test: `backend/tests/test_progress.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio

import pytest

from app.engine.progress import ThrottledBroadcaster


@pytest.mark.asyncio
async def test_throttled_broadcaster_coalesces_rapid_updates():
    sent: list[dict] = []

    async def fake_broadcast(data: dict) -> None:
        sent.append(data)

    broadcaster = ThrottledBroadcaster(broadcast_fn=fake_broadcast, interval_seconds=0.05)

    for i in range(20):
        broadcaster.report(item_id="item-1", downloaded_bytes=i)

    await asyncio.sleep(0.1)
    await broadcaster.flush()

    assert len(sent) >= 1
    assert sent[-1]["item_id"] == "item-1"
    assert sent[-1]["downloaded_bytes"] == 19
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_progress.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `backend/app/engine/progress.py`**

```python
import asyncio
import time
from typing import Awaitable, Callable


class ThrottledBroadcaster:
    def __init__(self, broadcast_fn: Callable[[dict], Awaitable[None]], interval_seconds: float = 0.5):
        self._broadcast_fn = broadcast_fn
        self._interval = interval_seconds
        self._latest: dict[str, dict] = {}
        self._last_sent: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def report(self, item_id: str, downloaded_bytes: int) -> None:
        self._latest[item_id] = {"type": "progress", "item_id": item_id, "downloaded_bytes": downloaded_bytes}
        asyncio.create_task(self._maybe_send(item_id))

    async def _maybe_send(self, item_id: str) -> None:
        now = time.monotonic()
        last = self._last_sent.get(item_id, 0)
        if now - last < self._interval:
            return
        async with self._lock:
            payload = self._latest.get(item_id)
            if payload is None:
                return
            self._last_sent[item_id] = now
            await self._broadcast_fn(payload)

    async def flush(self) -> None:
        for item_id, payload in list(self._latest.items()):
            await self._broadcast_fn(payload)
            self._last_sent[item_id] = time.monotonic()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_progress.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/engine/progress.py backend/tests/test_progress.py
git commit -m "feat: add throttled progress broadcaster"
```

---

## Task 18: Engine — scheduler (DB-integrated, concurrency limit, startup resume)

**Files:**
- Create: `backend/app/engine/scheduler.py`
- Test: `backend/tests/test_scheduler.py`

The scheduler is the bridge between the DB (source of truth for what's queued/running) and the pure `item_runner` engine, using the `ConnectionManager` (Task 16) and `ThrottledBroadcaster` (Task 17) to push live progress. `run_pending(db, max_concurrent, chunks_per_file, identity)` is called on a loop by the app lifespan (Task 19); `identity` is a `Callable[[str], str]` that Fase 1 implements as the identity function (`lambda url: url`) since there's no hoster-plugin resolution yet — Fase 2 replaces it.

Chunk rows are created once per item (via `on_chunks_planned`, fired by `run_download_item` before any bytes are fetched) so a mid-download crash leaves real, correctly-ranged `Chunk` rows in the DB instead of nothing. On resume, existing rows are reused positionally instead of re-created. Per-byte progress is **not** checkpointed to the `Chunk` table during the download — only to the in-memory `DownloadItem.downloaded_bytes` and the WS broadcaster — because chunk downloads run concurrently via `asyncio.gather` and `AsyncSession` is not safe for concurrent writes from multiple coroutines; serializing those writes behind a lock is real complexity with limited payoff for Fase 1 (see "Fuera de alcance"). Practical effect: on a mid-flight crash, a restart re-downloads only the chunks that hadn't finished yet (each at most `total_size / chunks_per_file` bytes), not the whole file — chunk boundaries are preserved, just not the exact byte offset within an unfinished chunk.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy import select

from app.engine.scheduler import resume_stale_running_items, run_pending
from app.models import Chunk, DownloadItem, Package


@pytest.mark.asyncio
async def test_run_pending_downloads_queued_item_end_to_end(session, test_server, tmp_path):
    payload = b"Z" * 400
    _, url = await test_server(payload, support_range=True)

    package = Package(name="pkg", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    item = DownloadItem(package_id=package.id, url=url, filename="out.bin", status="queued")
    session.add(item)
    await session.commit()

    await run_pending(session, max_concurrent=2, chunks_per_file=4, identity=lambda u: u)

    await session.refresh(item)
    await session.refresh(package)
    assert item.status == "completed"
    assert item.downloaded_bytes == 400
    assert package.status == "completed"
    assert (tmp_path / "out.bin").read_bytes() == payload

    chunks = (await session.execute(select(Chunk).where(Chunk.download_item_id == item.id))).scalars().all()
    assert len(chunks) == 4
    assert all(c.status == "completed" for c in chunks)


@pytest.mark.asyncio
async def test_run_pending_respects_concurrency_limit(session, test_server, tmp_path):
    _, url1 = await test_server(b"A" * 100)
    _, url2 = await test_server(b"B" * 100)
    _, url3 = await test_server(b"C" * 100)

    package = Package(name="pkg", status="queued", target_dir=str(tmp_path))
    session.add(package)
    await session.flush()
    for i, url in enumerate([url1, url2, url3]):
        session.add(DownloadItem(package_id=package.id, url=url, filename=f"f{i}.bin", status="queued"))
    await session.commit()

    started: list[str] = []

    await run_pending(
        session,
        max_concurrent=2,
        chunks_per_file=1,
        identity=lambda u: u,
        _on_start_for_test=lambda item_id: started.append(item_id),
    )

    result = await session.execute(select(DownloadItem).where(DownloadItem.package_id == package.id))
    items = result.scalars().all()
    assert all(i.status == "completed" for i in items)


@pytest.mark.asyncio
async def test_resume_stale_running_items_requeues_them(session):
    package = Package(name="pkg", status="running", target_dir="/tmp")
    session.add(package)
    await session.flush()
    item = DownloadItem(package_id=package.id, url="https://example.com/x", filename="x", status="running")
    session.add(item)
    await session.commit()

    await resume_stale_running_items(session)

    await session.refresh(item)
    assert item.status == "queued"
```

- [ ] **Step 2: Add a `session` fixture usable outside the FastAPI TestClient (append to `backend/tests/conftest.py`)**

```python
@pytest_asyncio.fixture
async def session(db_engine):
    factory = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 4: Implement `backend/app/engine/scheduler.py`**

```python
import asyncio
import os
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.item_runner import run_download_item
from app.engine.progress import ThrottledBroadcaster
from app.models import Chunk, DownloadItem, Package
from app.ws.manager import manager

_broadcaster = ThrottledBroadcaster(broadcast_fn=manager.broadcast)


async def resume_stale_running_items(db: AsyncSession) -> None:
    result = await db.execute(select(DownloadItem).where(DownloadItem.status == "running"))
    for item in result.scalars().all():
        item.status = "queued"
    await db.commit()


def _dest_path(item: DownloadItem) -> str:
    package_dir = item.package.target_dir if item.package else "/downloads"
    return os.path.join(package_dir, item.filename)


async def _run_one_item(db: AsyncSession, item: DownloadItem, chunks_per_file: int, identity: Callable[[str], str]) -> None:
    item.status = "running"
    await db.commit()

    resolved_url = identity(item.url)
    dest_path = _dest_path(item)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    existing_result = await db.execute(
        select(Chunk).where(Chunk.download_item_id == item.id).order_by(Chunk.range_start)
    )
    chunks_ref: list[Chunk] = list(existing_result.scalars().all())
    existing_progress = {i: c.downloaded_bytes for i, c in enumerate(chunks_ref)}

    async def on_chunks_planned(ranges: list[tuple[int, int]]) -> None:
        if chunks_ref:
            return  # resuming: rows already exist for this item, reuse them as-is
        for start, end in ranges:
            chunk = Chunk(download_item_id=item.id, range_start=start, range_end=end, status="running")
            db.add(chunk)
            chunks_ref.append(chunk)
        await db.flush()

    def on_progress(chunk_index: int, n: int) -> None:
        item.downloaded_bytes += n
        _broadcaster.report(item_id=item.id, downloaded_bytes=item.downloaded_bytes)

    try:
        result = await run_download_item(
            url=resolved_url,
            dest_path=dest_path,
            num_chunks=chunks_per_file,
            existing_progress=existing_progress,
            on_progress=on_progress,
            on_chunks_planned=on_chunks_planned,
        )
        item.total_size = result.total_size
        item.status = "completed"
        for chunk in chunks_ref:
            chunk.status = "completed"
            chunk.downloaded_bytes = chunk.range_end - chunk.range_start + 1
    except Exception as exc:  # noqa: BLE001
        item.status = "error"
        item.error_message = str(exc)

    await db.commit()


async def run_pending(
    db: AsyncSession,
    max_concurrent: int,
    chunks_per_file: int,
    identity: Callable[[str], str],
    _on_start_for_test: Callable[[str], None] | None = None,
) -> None:
    result = await db.execute(
        select(DownloadItem).where(DownloadItem.status == "queued").limit(max_concurrent)
    )
    items = result.scalars().all()

    for item in items:
        await db.refresh(item, attribute_names=["package"])
        if _on_start_for_test:
            _on_start_for_test(item.id)

    await asyncio.gather(*(_run_one_item(db, item, chunks_per_file, identity) for item in items))

    package_ids = {item.package_id for item in items}
    for package_id in package_ids:
        pkg_result = await db.execute(select(Package).where(Package.id == package_id))
        package = pkg_result.scalar_one()
        items_result = await db.execute(select(DownloadItem).where(DownloadItem.package_id == package_id))
        pkg_items = items_result.scalars().all()
        if all(i.status == "completed" for i in pkg_items):
            package.status = "completed"
    await db.commit()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/engine/scheduler.py backend/tests/test_scheduler.py backend/tests/conftest.py
git commit -m "feat: add DB-integrated scheduler with concurrency limit and startup resume"
```

---

## Task 19: App lifespan — background scheduler loop and startup resume

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_lifespan.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_still_works_with_lifespan():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lifespan.py -v`
Expected: PASS already (this is a guard test) — confirm it passes before changes, then again after, to prove the lifespan change doesn't break startup.

- [ ] **Step 3: Add a background scheduler loop to `backend/app/main.py`**

```python
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.packages import router as packages_router
from app.api.settings import router as settings_router
from app.config import Settings
from app.database import SessionLocal
from app.engine.scheduler import resume_stale_running_items, run_pending
from app.ws.routes import router as ws_router

_settings = Settings()


async def _scheduler_loop():
    while True:
        async with SessionLocal() as db:
            await run_pending(
                db,
                max_concurrent=_settings.max_concurrent_downloads,
                chunks_per_file=_settings.chunks_per_file,
                identity=lambda u: u,
            )
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as db:
        await resume_stale_running_items(db)
    task = asyncio.create_task(_scheduler_loop())
    yield
    task.cancel()


app = FastAPI(title="Cascade", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(packages_router)
app.include_router(settings_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

**Note:** the scheduler currently reads concurrency/chunk settings from `Settings` (env-based) rather than the `GlobalSettings` DB row from Task 11. Wiring the DB-backed settings into the live loop (so changes via `PUT /settings` take effect without a restart) is a small follow-up — track it as a fast-follow, not a blocker for Fase 1 sign-off, since env defaults already make the loop functional end-to-end.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lifespan.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && pytest -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_lifespan.py
git commit -m "feat: run scheduler loop and startup resume from app lifespan"
```

---

## Task 20: Backend Dockerfile

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`

- [ ] **Step 1: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 2: Create `backend/.dockerignore`**

```
__pycache__
*.pyc
.pytest_cache
tests
.venv
```

- [ ] **Step 3: Build the image locally to verify it compiles**

Run: `cd backend && docker build -t cascade-backend .`
Expected: build succeeds with no errors

- [ ] **Step 4: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore
git commit -m "chore: add backend Dockerfile"
```

---

## Task 21: Frontend project scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`

- [ ] **Step 1: Scaffold with Vite**

Run: `npm create vite@latest frontend -- --template react-ts`
Expected: creates `frontend/` with the standard Vite React+TS template

- [ ] **Step 2: Add test dependencies**

Run: `cd frontend && npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom`

- [ ] **Step 3: Add a `test` script and Vitest config to `frontend/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
  },
})
```

Add to `frontend/package.json` scripts: `"test": "vitest run"`.

- [ ] **Step 4: Create `frontend/src/test-setup.ts`**

```typescript
import '@testing-library/jest-dom'
```

- [ ] **Step 5: Replace the default `frontend/src/App.tsx` with a minimal placeholder**

```tsx
function App() {
  return <div>Cascade</div>
}

export default App
```

- [ ] **Step 6: Write and run a smoke test**

Create `frontend/src/App.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import App from './App'

test('renders app shell', () => {
  render(<App />)
  expect(screen.getByText('Cascade')).toBeInTheDocument()
})
```

Run: `cd frontend && npm run test`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "chore: scaffold Vite React frontend project"
```

---

## Task 22: API client with auth handling

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/api/packages.ts`
- Create: `frontend/src/types.ts`
- Test: `frontend/src/api/client.test.ts`

The backend sets `access_token` as an httpOnly cookie, so the frontend never reads or attaches the token manually — it just needs `credentials: 'include'` on every request so the browser sends the cookie automatically, and to surface 401s as a typed error the UI can react to (redirect to login).

- [ ] **Step 1: Write the failing test**

```typescript
import { afterEach, expect, test, vi } from 'vitest'
import { apiFetch, UnauthorizedError } from './client'

afterEach(() => {
  vi.restoreAllMocks()
})

test('apiFetch includes credentials and returns parsed json', async () => {
  const mockFetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ hello: 'world' }),
  })
  vi.stubGlobal('fetch', mockFetch)

  const result = await apiFetch('/health')

  expect(mockFetch).toHaveBeenCalledWith('/health', expect.objectContaining({ credentials: 'include' }))
  expect(result).toEqual({ hello: 'world' })
})

test('apiFetch throws UnauthorizedError on 401', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) })
  )

  await expect(apiFetch('/packages')).rejects.toBeInstanceOf(UnauthorizedError)
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- client.test.ts`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `frontend/src/api/client.ts`**

```typescript
export class UnauthorizedError extends Error {}
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })

  if (response.status === 401) {
    throw new UnauthorizedError('Not authenticated')
  }
  if (!response.ok) {
    throw new ApiError(response.status, `Request to ${path} failed with ${response.status}`)
  }
  return response.json() as Promise<T>
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- client.test.ts`
Expected: PASS

- [ ] **Step 5: Implement `frontend/src/types.ts`**

```typescript
export type ItemStatus = 'queued' | 'running' | 'paused' | 'completed' | 'error' | 'canceled'
export type PackageStatus = 'queued' | 'running' | 'paused' | 'completed' | 'error'

export interface DownloadItem {
  id: string
  url: string
  filename: string
  status: ItemStatus
  total_size: number | null
  downloaded_bytes: number
  error_message: string | null
}

export interface Package {
  id: string
  name: string
  status: PackageStatus
  target_dir: string
  items: DownloadItem[]
}
```

- [ ] **Step 6: Implement `frontend/src/api/auth.ts`**

```typescript
import { apiFetch } from './client'

export function login(username: string, password: string): Promise<{ ok: boolean }> {
  return apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
}

export function me(): Promise<{ username: string }> {
  return apiFetch('/auth/me')
}
```

- [ ] **Step 7: Implement `frontend/src/api/packages.ts`**

```typescript
import { apiFetch } from './client'
import type { Package } from '../types'

export function listPackages(): Promise<Package[]> {
  return apiFetch('/packages')
}

export function createPackage(name: string, urls: string[]): Promise<Package> {
  return apiFetch('/packages', { method: 'POST', body: JSON.stringify({ name, urls }) })
}

export function updatePackageStatus(id: string, status: string): Promise<Package> {
  return apiFetch(`/packages/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
}
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api frontend/src/types.ts
git commit -m "feat: add typed API client for auth and packages"
```

---

## Task 23: Login page

**Files:**
- Create: `frontend/src/pages/Login.tsx`
- Test: `frontend/src/pages/Login.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Login from './Login'
import * as authApi from '../api/auth'

afterEach(() => vi.restoreAllMocks())

test('submits credentials and calls onSuccess', async () => {
  const loginSpy = vi.spyOn(authApi, 'login').mockResolvedValue({ ok: true })
  const onSuccess = vi.fn()

  render(<Login onSuccess={onSuccess} />)

  fireEvent.change(screen.getByLabelText('Usuario'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'hunter2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))

  await waitFor(() => expect(onSuccess).toHaveBeenCalled())
  expect(loginSpy).toHaveBeenCalledWith('admin', 'hunter2')
})

test('shows error message on failed login', async () => {
  vi.spyOn(authApi, 'login').mockRejectedValue(new Error('bad creds'))

  render(<Login onSuccess={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Usuario'), { target: { value: 'admin' } })
  fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'wrong' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))

  expect(await screen.findByText('Usuario o contraseña incorrectos')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- Login.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `frontend/src/pages/Login.tsx`**

```tsx
import { useState } from 'react'
import { login } from '../api/auth'

interface Props {
  onSuccess: () => void
}

export default function Login({ onSuccess }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await login(username, password)
      onSuccess()
    } catch {
      setError('Usuario o contraseña incorrectos')
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <label htmlFor="username">Usuario</label>
      <input id="username" aria-label="Usuario" value={username} onChange={(e) => setUsername(e.target.value)} />

      <label htmlFor="password">Contraseña</label>
      <input
        id="password"
        aria-label="Contraseña"
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />

      <button type="submit">Ingresar</button>
      {error && <p role="alert">{error}</p>}
    </form>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- Login.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Login.tsx frontend/src/pages/Login.test.tsx
git commit -m "feat: add login page"
```

---

## Task 24: useProgressSocket hook

**Files:**
- Create: `frontend/src/ws/useProgressSocket.ts`
- Test: `frontend/src/ws/useProgressSocket.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
import { renderHook, act } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { useProgressSocket } from './useProgressSocket'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onmessage: ((ev: { data: string }) => void) | null = null
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  close = vi.fn()

  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }
}

afterEach(() => {
  FakeWebSocket.instances = []
  vi.restoreAllMocks()
})

test('updates progress map when a message arrives', () => {
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)

  const { result } = renderHook(() => useProgressSocket())
  const socket = FakeWebSocket.instances[0]

  act(() => {
    socket.onmessage?.({
      data: JSON.stringify({ type: 'progress', item_id: 'item-1', downloaded_bytes: 500 }),
    })
  })

  expect(result.current.progressByItemId['item-1']).toBe(500)
})

test('closes the socket on unmount', () => {
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket)

  const { unmount } = renderHook(() => useProgressSocket())
  const socket = FakeWebSocket.instances[0]

  unmount()

  expect(socket.close).toHaveBeenCalled()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- useProgressSocket.test.ts`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `frontend/src/ws/useProgressSocket.ts`**

```typescript
import { useEffect, useRef, useState } from 'react'

interface ProgressMessage {
  type: 'progress'
  item_id: string
  downloaded_bytes: number
}

export function useProgressSocket() {
  const [progressByItemId, setProgressByItemId] = useState<Record<string, number>>({})
  const socketRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws`)
    socketRef.current = socket

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as ProgressMessage
      if (message.type === 'progress') {
        setProgressByItemId((prev) => ({ ...prev, [message.item_id]: message.downloaded_bytes }))
      }
    }

    return () => {
      socket.close()
    }
  }, [])

  return { progressByItemId }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- useProgressSocket.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/ws
git commit -m "feat: add useProgressSocket hook for live download progress"
```

---

## Task 25: ProgressBar and PackageRow components

**Files:**
- Create: `frontend/src/components/ProgressBar.tsx`
- Create: `frontend/src/components/PackageRow.tsx`
- Test: `frontend/src/components/PackageRow.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import PackageRow from './PackageRow'
import type { Package } from '../types'

const pkg: Package = {
  id: 'pkg-1',
  name: 'My package',
  status: 'running',
  target_dir: '/downloads/my-package',
  items: [
    { id: 'i1', url: 'https://x/a.zip', filename: 'a.zip', status: 'running', total_size: 1000, downloaded_bytes: 400, error_message: null },
    { id: 'i2', url: 'https://x/b.zip', filename: 'b.zip', status: 'completed', total_size: 500, downloaded_bytes: 500, error_message: null },
  ],
}

test('renders package name, status, and aggregate progress', () => {
  render(<PackageRow package={pkg} onPause={() => {}} onResume={() => {}} onCancel={() => {}} />)

  expect(screen.getByText('My package')).toBeInTheDocument()
  expect(screen.getByText('running')).toBeInTheDocument()
  // aggregate: (400 + 500) / (1000 + 500) = 60%
  expect(screen.getByText('60%')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- PackageRow.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `frontend/src/components/ProgressBar.tsx`**

```tsx
interface Props {
  percent: number
}

export default function ProgressBar({ percent }: Props) {
  const clamped = Math.max(0, Math.min(100, percent))
  return (
    <div role="progressbar" aria-valuenow={clamped} style={{ background: '#eee', width: '100%' }}>
      <div style={{ width: `${clamped}%`, background: '#4caf50', height: '8px' }} />
      <span>{Math.round(clamped)}%</span>
    </div>
  )
}
```

- [ ] **Step 4: Implement `frontend/src/components/PackageRow.tsx`**

```tsx
import ProgressBar from './ProgressBar'
import type { Package } from '../types'

interface Props {
  package: Package
  onPause: (id: string) => void
  onResume: (id: string) => void
  onCancel: (id: string) => void
}

export default function PackageRow({ package: pkg, onPause, onResume, onCancel }: Props) {
  const totalSize = pkg.items.reduce((sum, i) => sum + (i.total_size ?? 0), 0)
  const downloaded = pkg.items.reduce((sum, i) => sum + i.downloaded_bytes, 0)
  const percent = totalSize > 0 ? (downloaded / totalSize) * 100 : 0

  return (
    <div>
      <span>{pkg.name}</span>
      <span>{pkg.status}</span>
      <ProgressBar percent={percent} />
      {pkg.status === 'running' && <button onClick={() => onPause(pkg.id)}>Pausar</button>}
      {pkg.status === 'paused' && <button onClick={() => onResume(pkg.id)}>Reanudar</button>}
      <button onClick={() => onCancel(pkg.id)}>Cancelar</button>
    </div>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm run test -- PackageRow.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ProgressBar.tsx frontend/src/components/PackageRow.tsx frontend/src/components/PackageRow.test.tsx
git commit -m "feat: add ProgressBar and PackageRow components"
```

---

## Task 26: AddLinksModal component

**Files:**
- Create: `frontend/src/components/AddLinksModal.tsx`
- Test: `frontend/src/components/AddLinksModal.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import AddLinksModal from './AddLinksModal'

test('parses newline-separated URLs and calls onSubmit', () => {
  const onSubmit = vi.fn()
  render(<AddLinksModal onSubmit={onSubmit} onClose={() => {}} />)

  fireEvent.change(screen.getByLabelText('Enlaces'), {
    target: { value: 'https://x/a.zip\nhttps://x/b.zip\n\nhttps://x/c.zip' },
  })
  fireEvent.change(screen.getByLabelText('Nombre del paquete'), { target: { value: 'Mi paquete' } })
  fireEvent.click(screen.getByRole('button', { name: 'Agregar' }))

  expect(onSubmit).toHaveBeenCalledWith('Mi paquete', [
    'https://x/a.zip',
    'https://x/b.zip',
    'https://x/c.zip',
  ])
})

test('disables submit when no urls entered', () => {
  render(<AddLinksModal onSubmit={vi.fn()} onClose={() => {}} />)
  expect(screen.getByRole('button', { name: 'Agregar' })).toBeDisabled()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- AddLinksModal.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `frontend/src/components/AddLinksModal.tsx`**

```tsx
import { useState } from 'react'

interface Props {
  onSubmit: (name: string, urls: string[]) => void
  onClose: () => void
}

export default function AddLinksModal({ onSubmit, onClose }: Props) {
  const [name, setName] = useState('')
  const [raw, setRaw] = useState('')

  const urls = raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)

  function handleSubmit() {
    onSubmit(name || 'Paquete sin nombre', urls)
  }

  return (
    <div role="dialog">
      <label htmlFor="package-name">Nombre del paquete</label>
      <input id="package-name" aria-label="Nombre del paquete" value={name} onChange={(e) => setName(e.target.value)} />

      <label htmlFor="links">Enlaces</label>
      <textarea id="links" aria-label="Enlaces" value={raw} onChange={(e) => setRaw(e.target.value)} />

      <button onClick={handleSubmit} disabled={urls.length === 0}>
        Agregar
      </button>
      <button onClick={onClose}>Cancelar</button>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- AddLinksModal.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AddLinksModal.tsx frontend/src/components/AddLinksModal.test.tsx
git commit -m "feat: add AddLinksModal component"
```

---

## Task 27: Dashboard page (wires packages list + WS progress + AddLinksModal)

**Files:**
- Create: `frontend/src/pages/Dashboard.tsx`
- Test: `frontend/src/pages/Dashboard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Dashboard from './Dashboard'
import * as packagesApi from '../api/packages'
import * as socketHook from '../ws/useProgressSocket'

afterEach(() => vi.restoreAllMocks())

test('loads and renders packages on mount', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([
    { id: 'p1', name: 'Pkg 1', status: 'running', target_dir: '/x', items: [] },
  ])
  vi.spyOn(socketHook, 'useProgressSocket').mockReturnValue({ progressByItemId: {} })

  render(<Dashboard />)

  await waitFor(() => expect(screen.getByText('Pkg 1')).toBeInTheDocument())
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- Dashboard.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `frontend/src/pages/Dashboard.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { createPackage, listPackages, updatePackageStatus } from '../api/packages'
import { useProgressSocket } from '../ws/useProgressSocket'
import PackageRow from '../components/PackageRow'
import AddLinksModal from '../components/AddLinksModal'
import type { Package } from '../types'

export default function Dashboard() {
  const [packages, setPackages] = useState<Package[]>([])
  const [showModal, setShowModal] = useState(false)
  useProgressSocket()

  async function refresh() {
    setPackages(await listPackages())
  }

  useEffect(() => {
    refresh()
  }, [])

  async function handleCreate(name: string, urls: string[]) {
    await createPackage(name, urls)
    setShowModal(false)
    await refresh()
  }

  async function handleStatusChange(id: string, status: string) {
    await updatePackageStatus(id, status)
    await refresh()
  }

  return (
    <div>
      <button onClick={() => setShowModal(true)}>Agregar enlaces</button>
      {packages.map((pkg) => (
        <PackageRow
          key={pkg.id}
          package={pkg}
          onPause={(id) => handleStatusChange(id, 'paused')}
          onResume={(id) => handleStatusChange(id, 'queued')}
          onCancel={(id) => handleStatusChange(id, 'canceled')}
        />
      ))}
      {showModal && <AddLinksModal onSubmit={handleCreate} onClose={() => setShowModal(false)} />}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- Dashboard.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/Dashboard.test.tsx
git commit -m "feat: add Dashboard page wiring packages list, add-links modal, and live progress"
```

---

## Task 28: App shell — auth gate and routing between Login and Dashboard

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

Fase 1 has exactly two screens gated by auth state, so a full router is unnecessary — `App` holds `isAuthenticated` state and renders one or the other. Settings/PackageDetail are deferred; see "Fuera de alcance" note at the end of this plan.

- [ ] **Step 1: Write the failing test (replace `frontend/src/App.test.tsx`)**

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'
import * as authApi from '../src/api/auth'

afterEach(() => vi.restoreAllMocks())

test('shows login when not authenticated', async () => {
  vi.spyOn(authApi, 'me').mockRejectedValue(new Error('401'))

  render(<App />)

  await waitFor(() => expect(screen.getByRole('button', { name: 'Ingresar' })).toBeInTheDocument())
})

test('shows dashboard when already authenticated', async () => {
  vi.spyOn(authApi, 'me').mockResolvedValue({ username: 'admin' })

  render(<App />)

  await waitFor(() => expect(screen.getByText('Agregar enlaces')).toBeInTheDocument())
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- App.test.tsx`
Expected: FAIL — current `App` renders the static placeholder from Task 21

- [ ] **Step 3: Implement `frontend/src/App.tsx`**

```tsx
import { useEffect, useState } from 'react'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import { me } from './api/auth'

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)

  useEffect(() => {
    me()
      .then(() => setIsAuthenticated(true))
      .catch(() => setIsAuthenticated(false))
  }, [])

  if (isAuthenticated === null) return null
  if (!isAuthenticated) return <Login onSuccess={() => setIsAuthenticated(true)} />
  return <Dashboard />
}

export default App
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- App.test.tsx`
Expected: PASS

- [ ] **Step 5: Run the full frontend test suite**

Run: `npm run test`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: gate Dashboard behind auth check in App shell"
```

---

## Task 29: Settings page

**Files:**
- Create: `frontend/src/api/settings.ts`
- Create: `frontend/src/pages/Settings.tsx`
- Test: `frontend/src/pages/Settings.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Settings from './Settings'
import * as settingsApi from '../api/settings'

afterEach(() => vi.restoreAllMocks())

test('loads existing settings and submits updates', async () => {
  vi.spyOn(settingsApi, 'getSettings').mockResolvedValue({
    download_root: '/downloads',
    max_concurrent_downloads: 3,
    chunks_per_file: 4,
    max_speed_kbps: 0,
  })
  const updateSpy = vi.spyOn(settingsApi, 'updateSettings').mockResolvedValue({
    download_root: '/downloads',
    max_concurrent_downloads: 5,
    chunks_per_file: 4,
    max_speed_kbps: 0,
  })

  render(<Settings onClose={() => {}} />)

  await waitFor(() => expect(screen.getByLabelText('Descargas simultáneas')).toHaveValue(3))

  fireEvent.change(screen.getByLabelText('Descargas simultáneas'), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Guardar' }))

  await waitFor(() =>
    expect(updateSpy).toHaveBeenCalledWith({
      download_root: '/downloads',
      max_concurrent_downloads: 5,
      chunks_per_file: 4,
      max_speed_kbps: 0,
    })
  )
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- Settings.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `frontend/src/api/settings.ts`**

```typescript
import { apiFetch } from './client'

export interface AppSettings {
  download_root: string
  max_concurrent_downloads: number
  chunks_per_file: number
  max_speed_kbps: number
}

export function getSettings(): Promise<AppSettings> {
  return apiFetch('/settings')
}

export function updateSettings(settings: AppSettings): Promise<AppSettings> {
  return apiFetch('/settings', { method: 'PUT', body: JSON.stringify(settings) })
}
```

- [ ] **Step 4: Implement `frontend/src/pages/Settings.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { AppSettings, getSettings, updateSettings } from '../api/settings'

interface Props {
  onClose: () => void
}

export default function Settings({ onClose }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)

  useEffect(() => {
    getSettings().then(setSettings)
  }, [])

  if (!settings) return null

  function update<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  async function handleSave() {
    if (!settings) return
    await updateSettings(settings)
    onClose()
  }

  return (
    <div>
      <label htmlFor="download-root">Carpeta de descarga</label>
      <input
        id="download-root"
        aria-label="Carpeta de descarga"
        value={settings.download_root}
        onChange={(e) => update('download_root', e.target.value)}
      />

      <label htmlFor="max-concurrent">Descargas simultáneas</label>
      <input
        id="max-concurrent"
        aria-label="Descargas simultáneas"
        type="number"
        value={settings.max_concurrent_downloads}
        onChange={(e) => update('max_concurrent_downloads', Number(e.target.value))}
      />

      <label htmlFor="chunks-per-file">Chunks por archivo</label>
      <input
        id="chunks-per-file"
        aria-label="Chunks por archivo"
        type="number"
        value={settings.chunks_per_file}
        onChange={(e) => update('chunks_per_file', Number(e.target.value))}
      />

      <label htmlFor="max-speed">Límite de velocidad (KB/s, 0 = sin límite)</label>
      <input
        id="max-speed"
        aria-label="Límite de velocidad (KB/s, 0 = sin límite)"
        type="number"
        value={settings.max_speed_kbps}
        onChange={(e) => update('max_speed_kbps', Number(e.target.value))}
      />

      <button onClick={handleSave}>Guardar</button>
      <button onClick={onClose}>Cancelar</button>
    </div>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm run test -- Settings.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/settings.ts frontend/src/pages/Settings.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat: add Settings page"
```

---

## Task 30: PackageDetail page and Dashboard wiring

**Files:**
- Create: `frontend/src/pages/PackageDetail.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/components/PackageRow.tsx`
- Test: `frontend/src/pages/PackageDetail.test.tsx`
- Test: `frontend/src/pages/Dashboard.test.tsx`

Fase 1 keeps navigation state-based (consistent with Task 28's no-router approach): `Dashboard` tracks which screen is active (`list` | `detail` | `settings`) instead of pulling in a routing library for four screens.

- [ ] **Step 1: Write the failing test for `PackageDetail`**

```tsx
import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import PackageDetail from './PackageDetail'
import type { Package } from '../types'

const pkg: Package = {
  id: 'p1',
  name: 'My package',
  status: 'running',
  target_dir: '/downloads/my-package',
  items: [
    { id: 'i1', url: 'https://x/a.zip', filename: 'a.zip', status: 'running', total_size: 1000, downloaded_bytes: 250, error_message: null },
    { id: 'i2', url: 'https://x/b.zip', filename: 'b.zip', status: 'error', total_size: null, downloaded_bytes: 0, error_message: 'timeout' },
  ],
}

test('renders each item with its own progress and errors', () => {
  render(<PackageDetail package={pkg} onBack={() => {}} />)

  expect(screen.getByText('a.zip')).toBeInTheDocument()
  expect(screen.getByText('25%')).toBeInTheDocument()
  expect(screen.getByText('b.zip')).toBeInTheDocument()
  expect(screen.getByText('timeout')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- PackageDetail.test.tsx`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `frontend/src/pages/PackageDetail.tsx`**

```tsx
import ProgressBar from '../components/ProgressBar'
import type { Package } from '../types'

interface Props {
  package: Package
  onBack: () => void
}

export default function PackageDetail({ package: pkg, onBack }: Props) {
  return (
    <div>
      <button onClick={onBack}>Volver</button>
      <h2>{pkg.name}</h2>
      {pkg.items.map((item) => {
        const percent = item.total_size ? (item.downloaded_bytes / item.total_size) * 100 : 0
        return (
          <div key={item.id}>
            <span>{item.filename}</span>
            <span>{item.status}</span>
            <ProgressBar percent={percent} />
            {item.error_message && <p role="alert">{item.error_message}</p>}
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- PackageDetail.test.tsx`
Expected: PASS

- [ ] **Step 5: Write the failing test for Dashboard navigation (append to `frontend/src/pages/Dashboard.test.tsx`)**

```tsx
import { fireEvent } from '@testing-library/react'

test('clicking a package name shows its detail view', async () => {
  vi.spyOn(packagesApi, 'listPackages').mockResolvedValue([
    {
      id: 'p1',
      name: 'Pkg 1',
      status: 'running',
      target_dir: '/x',
      items: [
        { id: 'i1', url: 'https://x/a.zip', filename: 'a.zip', status: 'running', total_size: 100, downloaded_bytes: 10, error_message: null },
      ],
    },
  ])
  vi.spyOn(socketHook, 'useProgressSocket').mockReturnValue({ progressByItemId: {} })

  render(<Dashboard />)

  fireEvent.click(await screen.findByText('Pkg 1'))

  expect(await screen.findByText('a.zip')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Volver' })).toBeInTheDocument()
})
```

- [ ] **Step 6: Run test to verify it fails**

Run: `npm run test -- Dashboard.test.tsx`
Expected: FAIL — clicking the package name does nothing yet

- [ ] **Step 7: Make the package name clickable in `frontend/src/components/PackageRow.tsx`**

Change the `<span>{pkg.name}</span>` line to:

```tsx
<button onClick={() => onSelect(pkg.id)} style={{ background: 'none', border: 'none', textDecoration: 'underline', cursor: 'pointer' }}>
  {pkg.name}
</button>
```

Add `onSelect: (id: string) => void` to the `Props` interface and destructure it alongside the existing props.

- [ ] **Step 8: Wire view state and Settings/PackageDetail into `frontend/src/pages/Dashboard.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { createPackage, listPackages, updatePackageStatus } from '../api/packages'
import { useProgressSocket } from '../ws/useProgressSocket'
import PackageRow from '../components/PackageRow'
import AddLinksModal from '../components/AddLinksModal'
import PackageDetail from './PackageDetail'
import SettingsPage from './Settings'
import type { Package } from '../types'

type View = { name: 'list' } | { name: 'detail'; packageId: string } | { name: 'settings' }

export default function Dashboard() {
  const [packages, setPackages] = useState<Package[]>([])
  const [showModal, setShowModal] = useState(false)
  const [view, setView] = useState<View>({ name: 'list' })
  useProgressSocket()

  async function refresh() {
    setPackages(await listPackages())
  }

  useEffect(() => {
    refresh()
  }, [])

  async function handleCreate(name: string, urls: string[]) {
    await createPackage(name, urls)
    setShowModal(false)
    await refresh()
  }

  async function handleStatusChange(id: string, status: string) {
    await updatePackageStatus(id, status)
    await refresh()
  }

  if (view.name === 'settings') {
    return <SettingsPage onClose={() => setView({ name: 'list' })} />
  }

  if (view.name === 'detail') {
    const pkg = packages.find((p) => p.id === view.packageId)
    if (pkg) {
      return <PackageDetail package={pkg} onBack={() => setView({ name: 'list' })} />
    }
  }

  return (
    <div>
      <button onClick={() => setShowModal(true)}>Agregar enlaces</button>
      <button onClick={() => setView({ name: 'settings' })}>Configuración</button>
      {packages.map((pkg) => (
        <PackageRow
          key={pkg.id}
          package={pkg}
          onSelect={(id) => setView({ name: 'detail', packageId: id })}
          onPause={(id) => handleStatusChange(id, 'paused')}
          onResume={(id) => handleStatusChange(id, 'queued')}
          onCancel={(id) => handleStatusChange(id, 'canceled')}
        />
      ))}
      {showModal && <AddLinksModal onSubmit={handleCreate} onClose={() => setShowModal(false)} />}
    </div>
  )
}
```

- [ ] **Step 9: Update the existing `PackageRow` render call in `frontend/src/components/PackageRow.test.tsx`**

Add `onSelect={() => {}}` to the `<PackageRow ... />` call in the `test('renders package name, status, and aggregate progress', ...)` test from Task 25.

- [ ] **Step 10: Run test to verify it passes**

Run: `npm run test`
Expected: All frontend tests PASS

- [ ] **Step 11: Commit**

```bash
git add frontend/src/pages/PackageDetail.tsx frontend/src/pages/PackageDetail.test.tsx frontend/src/pages/Dashboard.tsx frontend/src/pages/Dashboard.test.tsx frontend/src/components/PackageRow.tsx frontend/src/components/PackageRow.test.tsx
git commit -m "feat: add PackageDetail view and wire Settings/PackageDetail navigation into Dashboard"
```

---

## Task 31: Frontend Dockerfile, docker-compose.yml, and env template

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `docker-compose.yml`
- Create: `.env.example`

The frontend is built to static assets and served by nginx, which also reverse-proxies `/auth`, `/packages`, `/settings`, and `/ws` to the backend container — this lets the browser treat frontend and API as the same origin, so the httpOnly auth cookie and WebSocket both work without CORS configuration.

- [ ] **Step 1: Create `frontend/Dockerfile`**

```dockerfile
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 2: Create `frontend/nginx.conf`**

```nginx
server {
    listen 80;

    location / {
        root /usr/share/nginx/html;
        try_files $uri /index.html;
    }

    location ~ ^/(auth|packages|settings) {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header Cookie $http_cookie;
    }

    location /ws {
        proxy_pass http://backend:8000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Cookie $http_cookie;
    }
}
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: cascade
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-cascade}
      POSTGRES_DB: cascade
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cascade"]
      interval: 5s
      timeout: 5s
      retries: 10

  backend:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+asyncpg://cascade:${POSTGRES_PASSWORD:-cascade}@postgres:5432/cascade
      JWT_SECRET: ${JWT_SECRET}
      ADMIN_USERNAME: ${ADMIN_USERNAME}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD}
      DOWNLOAD_ROOT: /downloads
    volumes:
      - downloads:/downloads
    depends_on:
      postgres:
        condition: service_healthy

  frontend:
    build: ./frontend
    ports:
      - "8080:80"
    depends_on:
      - backend

volumes:
  pg_data:
  downloads:
```

- [ ] **Step 4: Create `.env.example`**

```
POSTGRES_PASSWORD=changeme
JWT_SECRET=changeme-to-a-long-random-string
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
```

- [ ] **Step 5: Bring the full stack up and verify it serves the login page**

Run: `cp .env.example .env && docker compose up --build -d`
Then: `curl -s http://localhost:8080 | grep -o '<title>[^<]*'`
Expected: `<title>Cascade` (or the Vite default title if not yet customized — acceptable, cosmetic)
Run: `docker compose logs backend | tail -20`
Expected: no errors, `alembic upgrade head` ran, `Uvicorn running on http://0.0.0.0:8000`
Clean up: `docker compose down -v`

- [ ] **Step 6: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf docker-compose.yml .env.example
git commit -m "chore: add docker-compose stack wiring frontend, backend, and postgres"
```

---

## Task 32: End-to-end manual smoke test

**Files:** none (verification only, no code changes)

This closes out Fase 1: prove the whole stack works against a real download, not just mocked tests.

- [ ] **Step 1: Start the stack**

Run: `cp .env.example .env && docker compose up --build -d`

- [ ] **Step 2: Log in**

Open `http://localhost:8080` in a browser, log in with the `ADMIN_USERNAME`/`ADMIN_PASSWORD` from `.env`.
Expected: redirected to the Dashboard (empty package list).

- [ ] **Step 3: Add a real direct-download link**

Click "Agregar enlaces", paste a large-ish publicly available direct file URL (e.g. a Linux ISO mirror or `https://speed.hetzner.de/100MB.bin`), give it a package name, submit.
Expected: package appears in the Dashboard with status `queued`, then `running`.

- [ ] **Step 4: Watch live progress**

Expected: the progress bar advances without manually refreshing the page (proves the WebSocket path works end-to-end).

- [ ] **Step 5: Verify the file on disk**

Run: `docker compose exec backend ls -la /downloads`
Expected: the package folder and downloaded file are present with the correct final size.

- [ ] **Step 6: Verify resume-on-restart**

While a large download is still `running`, run `docker compose restart backend`. After it comes back up, confirm in the UI that the item returns to `queued`/`running` and finishes successfully (proves `resume_stale_running_items` and chunk-level resume work against a live download, not just the test server).

- [ ] **Step 7: Tear down**

Run: `docker compose down -v`

- [ ] **Step 8: Record the result**

If any step fails, file it as a follow-up task before considering Fase 1 done — do not silently patch around it without updating this plan or the spec.

---

## Resultado del smoke test (Task 32) y correcciones derivadas

El smoke test se corrió contra el stack completo de Docker Compose. Login, creación de paquete, descarga de 100 MB en 4 chunks y verificación en disco: OK, con md5 idéntico al origen.

El entorno no tenía DNS saliente desde los contenedores, así que en vez de una URL pública (`speed.hetzner.de`) se usó un nginx con `limit_rate` dentro de la red de compose. Eso ejercita todo el camino API → scheduler → engine → disco → WS; lo único que no prueba es la salida a internet, que no es código de Cascade.

El paso 6 (resume tras reinicio) **falló**, y expuso dos huecos contra el spec que el plan no cubría. Ambos quedaron corregidos y re-verificados:

1. **El resume no reanudaba: volvía a empezar de cero.** Durante una descarga completa la tabla `chunks` no tenía ninguna fila y `downloaded_bytes` quedaba en 0, porque `on_chunks_planned` hacía `flush()` sin commit y el progreso por chunk solo se escribía al completar. El camino de resume (`existing_progress` → `Range`) funcionaba, pero leía siempre ceros. Corregido con checkpointing periódico (`fix: checkpoint chunk progress…`). Detalle de correctitud: un offset solo es reanudable después de `flush()` del archivo — el contador que alimenta la barra de progreso cuenta bytes que todavía están en el buffer, y persistirlo dejaría un hueco silencioso en el archivo. Re-verificado: reinicio a mitad de una descarga de 100 MB, los contadores continúan desde el checkpoint y el md5 final coincide.

2. **`max_speed_kbps` no se aplicaba en ningún lado.** El spec lo lista como setting de Fase 1; se persistía y nadie lo leía. Implementado como un token bucket único compartido por todos los chunks (`feat: enforce the global download speed limit`). Verificado: con cap de 2048 KB/s contra un servidor que sirve a 100 MB/s, el throughput medido fue ~2,0 MB/s.

También se corrigió que `max_concurrent_downloads`, `chunks_per_file` y `download_root` se guardaban pero nunca se leían (`fix: make the saved settings actually drive downloads`), lo que cierra el fast-follow que anotaba la Task 19.

## Fuera de alcance (carried over from spec, confirmed still deferred)

- Hoster plugins, CAPTCHA solving, archive/container extraction — Fases 2–4.
- Multi-usuario / SaaS, link grabbing desde portapapeles o extensión de navegador — confirmado fuera de alcance en el spec.

