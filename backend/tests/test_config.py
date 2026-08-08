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
