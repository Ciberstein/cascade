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
    # Lets the API run without the download engine attached - used by the test
    # suite, which has no live Postgres for the loop to poll.
    scheduler_enabled: bool = True
