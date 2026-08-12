from app.config import Settings


def test_settings_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/cascade")

    settings = Settings()

    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/cascade"
    assert settings.download_root == "/downloads"


def test_the_engine_defaults_are_sane_without_any_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/cascade")

    settings = Settings()

    # Ya no hay JWT_SECRET ni credenciales de admin: sin login, no hacen falta.
    assert settings.max_concurrent_downloads >= 1
    assert settings.chunks_per_file >= 1
    assert settings.max_concurrent_crawls >= 1


def test_a_managed_postgres_url_gets_an_async_driver():
    # Managed providers hand out postgres:// or postgresql://, which SQLAlchemy
    # resolves to psycopg2 - synchronous, and create_async_engine refuses it.
    # Rewriting lets the platform's own variable be referenced as-is.
    assert Settings(database_url="postgres://u:p@h:5432/d").database_url == (
        "postgresql+asyncpg://u:p@h:5432/d"
    )
    assert Settings(database_url="postgresql://u:p@h:5432/d").database_url == (
        "postgresql+asyncpg://u:p@h:5432/d"
    )


def test_a_url_that_names_its_driver_is_left_alone():
    # Naming a driver is a deliberate choice - the test suite's aiosqlite among
    # them - and second-guessing it would break the suite it came from.
    for url in ("postgresql+asyncpg://u:p@h/d", "sqlite+aiosqlite:///:memory:"):
        assert Settings(database_url=url).database_url == url
