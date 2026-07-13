from typing import Literal

from pydantic import BaseModel, Field


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

    model_config = {"from_attributes": True}


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

    model_config = {"from_attributes": True}


class UpdateSettingsRequest(BaseModel):
    download_root: str
    max_concurrent_downloads: int = Field(ge=1, le=20)
    chunks_per_file: int = Field(ge=1, le=16)
    max_speed_kbps: int = Field(ge=0)
