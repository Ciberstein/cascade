from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    download_root: str = "/downloads"
    #: Built SPA, relative to the working directory. Present in the container
    #: image; absent when running uvicorn straight from a checkout, where Vite
    #: serves the frontend on its own port instead.
    static_dir: str = "static"
    max_concurrent_downloads: int = 3
    chunks_per_file: int = 4
    max_concurrent_crawls: int = 5
    #: Grace period after a file is retrieved, before it is deleted from the
    #: server. Deliberately not zero: if the browser's download breaks at 90%,
    #: deleting instantly would leave the user with nothing and the hoster's
    #: copy already spent.
    retrieval_grace_minutes: int = 30
    #: Ceiling for whatever nobody retrieves. Without it, a file the user never
    #: came back for stays forever and the disk grows again.
    max_retention_hours: int = 24
    # Lets the API run without the download engine attached - used by the test
    # suite, which has no live Postgres for the loop to poll.
    scheduler_enabled: bool = True

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, url: str) -> str:
        """Forces an async driver onto a URL that doesn't name one.

        Managed Postgres providers hand out `postgres://` or `postgresql://`,
        which SQLAlchemy resolves to psycopg2 - a synchronous driver that
        create_async_engine rejects outright. Rewriting here means the platform's
        variable can be referenced as-is instead of being copied and edited by
        hand, which is the kind of duplication that goes stale on the first
        credential rotation.

        A URL that already names its driver ("+asyncpg", "+aiosqlite") is left
        alone: it was chosen deliberately.
        """
        scheme, separator, rest = url.partition("://")
        if not separator or "+" in scheme:
            return url
        if scheme in ("postgres", "postgresql"):
            return f"postgresql+asyncpg://{rest}"
        return url
