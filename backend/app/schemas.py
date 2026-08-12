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
    #: True once the file has been freed from the server. The row stays in the
    #: history; what went is the file.
    file_removed: bool
    #: Ya retirado por el usuario. El navegador no vuelve a dispararlo solo.
    retrieved: bool
    #: "video"/"audio" while a quality that arrived as separate tracks is
    #: downloading; None the rest of the time. The audio part is not listed: it
    #: is a means, not a download the user asked for. Its progress does count
    #: towards the package total, or the bar would lie.
    merge_role: str | None

    model_config = {"from_attributes": True}

    @field_serializer("retry_after")
    def _utc(self, value: dt.datetime | None) -> str | None:
        """Serialises with an explicit "Z".

        The column stores UTC without tzinfo, so by default it would come out as
        "2026-08-08T14:30:00". JavaScript parses an ISO string with no offset as
        *local* time, and the UI would show the wait shifted by the timezone -
        three hours here. Precisely the value whose only job is to stop the user
        confusing "scheduled" with "broken".
        """
        if value is None:
            return None
        aware = value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
        return aware.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


class UpdatePackageRequest(BaseModel):
    """Cambiar el estado, el nombre, o ambos."""

    status: Literal["queued", "paused", "canceled"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)


class PackageResponse(BaseModel):
    id: str
    name: str
    status: str
    target_dir: str
    items: list[DownloadItemResponse]

    model_config = {"from_attributes": True}


class SettingsResponse(BaseModel):
    """Only what the user gets to decide.

    The server folder is absent: the file is handed to the browser, which saves
    it wherever it saves everything. Where the server parks it meanwhile is an
    infrastructure decision (DOWNLOAD_ROOT), not a user option.
    """

    max_concurrent_downloads: int
    chunks_per_file: int
    max_speed_kbps: int
    max_concurrent_crawls: int

    model_config = {"from_attributes": True}


class UpdateSettingsRequest(BaseModel):
    max_concurrent_downloads: int = Field(ge=1, le=20)
    chunks_per_file: int = Field(ge=1, le=16)
    max_speed_kbps: int = Field(ge=0)
    max_concurrent_crawls: int = Field(ge=1, le=20)


class CreateCrawlJobRequest(BaseModel):
    links: str = Field(min_length=1)

    @field_validator("links")
    @classmethod
    def at_least_one_link(cls, value: str) -> str:
        # min_length=1 would let a textarea of nothing but spaces through and
        # produce a job that discovers nothing, without telling the user why.
        if not [line for line in value.splitlines() if line.strip()]:
            raise ValueError("at least one link is required")
        return value


class VariantResponse(BaseModel):
    id: str
    label: str
    height: int | None = None
    size: int | None = None
    needs_merge: bool = False
    ext: str | None = None


class CrawlResultResponse(BaseModel):
    id: str
    url: str
    filename: str
    size: int | None
    hoster: str
    status: str
    error_message: str | None
    #: Qualities to choose from. Empty for anything that isn't video.
    variants: list[VariantResponse] = Field(default_factory=list)

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
    #: Calidad elegida por resultado: {id_de_resultado: id_de_variante}. Lo que
    #: no aparezca usa la mejor disponible.
    quality: dict[str, str] = Field(default_factory=dict)


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    # A deliberately low floor, but not zero: the account protects a download
    # list, not a bank account, and a high minimum pushes people to reuse.
    password: str = Field(min_length=8, max_length=200)


class AccountResponse(BaseModel):
    """username is None when this browser hasn't registered yet."""

    username: str | None


class OwnerTokenResponse(BaseModel):
    owner_token: str
