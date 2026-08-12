from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    download_root: str = "/downloads"
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
