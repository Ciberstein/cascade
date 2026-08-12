from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    download_root: str = "/downloads"
    max_concurrent_downloads: int = 3
    chunks_per_file: int = 4
    max_concurrent_crawls: int = 5
    #: Margen tras retirar un archivo antes de borrarlo del servidor. No es
    #: cero a propósito: si la descarga del navegador se corta al 90%, borrarlo
    #: al instante dejaría al usuario sin nada y con la copia del hoster ya
    #: consumida.
    retrieval_grace_minutes: int = 30
    #: Tope para lo que nadie retira. Sin esto, un archivo que el usuario nunca
    #: fue a buscar se queda para siempre y el disco vuelve a crecer.
    max_retention_hours: int = 24
    # Lets the API run without the download engine attached - used by the test
    # suite, which has no live Postgres for the loop to poll.
    scheduler_enabled: bool = True
