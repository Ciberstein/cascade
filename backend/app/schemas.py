import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_serializer, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool = True


class UserOut(BaseModel):
    """Safe, public projection of a User -- excludes password_hash.

    Use this (or a hand-built dict) whenever a user-returning endpoint's
    response body is derived from a User ORM object. Never return the ORM
    object directly (e.g. via a loosely-scoped response_model or
    jsonable_encoder), since it serializes password_hash verbatim.
    """

    id: str
    username: str

    model_config = {"from_attributes": True}


class CreatePackageRequest(BaseModel):
    name: str = Field(min_length=1)
    urls: list[str] = Field(min_length=1)


class DownloadItemResponse(BaseModel):
    id: str
    url: str
    filename: str
    status: str
    total_size: int | None
    downloaded_bytes: int
    error_message: str | None
    hoster: str
    retry_after: dt.datetime | None

    model_config = {"from_attributes": True}

    @field_serializer("retry_after")
    def _utc(self, value: dt.datetime | None) -> str | None:
        """Serializa con "Z" explícito.

        La columna guarda UTC sin tzinfo, así que por defecto saldría como
        "2026-08-08T14:30:00". Un string ISO sin offset lo parsea JavaScript
        como hora *local*, y la UI mostraría la espera corrida por el huso -
        tres horas en este caso. Justo el dato cuya única función es que el
        usuario no confunda "agendado" con "roto".
        """
        if value is None:
            return None
        aware = value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
        return aware.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


class UpdatePackageStatusRequest(BaseModel):
    status: Literal["queued", "paused", "canceled"]


class PackageResponse(BaseModel):
    id: str
    name: str
    status: str
    target_dir: str
    items: list[DownloadItemResponse]

    model_config = {"from_attributes": True}


class SettingsResponse(BaseModel):
    download_root: str
    max_concurrent_downloads: int
    chunks_per_file: int
    max_speed_kbps: int
    max_concurrent_crawls: int

    model_config = {"from_attributes": True}


class UpdateSettingsRequest(BaseModel):
    download_root: str
    max_concurrent_downloads: int = Field(ge=1, le=20)
    chunks_per_file: int = Field(ge=1, le=16)
    max_speed_kbps: int = Field(ge=0)
    max_concurrent_crawls: int = Field(ge=1, le=20)


class CreateCrawlJobRequest(BaseModel):
    links: str = Field(min_length=1)

    @field_validator("links")
    @classmethod
    def at_least_one_link(cls, value: str) -> str:
        # min_length=1 dejaría pasar un textarea con solo espacios y produciría
        # un job que no descubre nada, sin decirle al usuario por qué.
        if not [line for line in value.splitlines() if line.strip()]:
            raise ValueError("hace falta al menos un enlace")
        return value


class CrawlResultResponse(BaseModel):
    id: str
    url: str
    filename: str
    size: int | None
    hoster: str
    status: str
    error_message: str | None

    model_config = {"from_attributes": True}


class CrawlJobResponse(BaseModel):
    id: str
    raw_input: str
    status: str
    error_message: str | None
    results: list[CrawlResultResponse]

    model_config = {"from_attributes": True}


class PromoteRequest(BaseModel):
    name: str = Field(min_length=1)
    result_ids: list[str] = Field(min_length=1)
