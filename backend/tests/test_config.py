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
