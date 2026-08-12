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
    #: True cuando el archivo ya se liberó del servidor. La fila queda en el
    #: historial; lo que se fue es el archivo.
    file_removed: bool
    #: Ya retirado por el usuario. El navegador no vuelve a dispararlo solo.
    retrieved: bool
    #: "video"/"audio" mientras una calidad que vino en pistas separadas se
    #: está bajando; None el resto del tiempo. La parte de audio no se lista:
    #: es un medio, no una descarga que el usuario pidió. Su progreso sí cuenta
    #: en el total del paquete, o la barra mentiría.
    merge_role: str | None

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
    """Solo lo que el usuario puede decidir.

    La carpeta del servidor no está: el archivo se entrega al navegador y este
    lo guarda donde guarda todo. Dónde lo deja el servidor mientras tanto es
    una decisión de infraestructura (DOWNLOAD_ROOT), no una opción de usuario.
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
        # min_length=1 dejaría pasar un textarea con solo espacios y produciría
        # un job que no descubre nada, sin decirle al usuario por qué.
        if not [line for line in value.splitlines() if line.strip()]:
            raise ValueError("hace falta al menos un enlace")
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
    #: Calidades entre las que elegir. Vacío para lo que no es video.
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
    # Piso deliberadamente bajo pero no nulo: la cuenta protege una lista de
    # descargas, no una cuenta bancaria, y un mínimo alto empuja a reutilizar.
    password: str = Field(min_length=8, max_length=200)


class AccountResponse(BaseModel):
    """username es None cuando este navegador todavía no se registró."""

    username: str | None


class OwnerTokenResponse(BaseModel):
    owner_token: str
