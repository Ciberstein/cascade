"""El contrato que todo hoster implementa. Sin I/O: solo tipos y errores."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CrawledFile:
    """Un archivo concreto descubierto detrás de un link."""

    url: str
    filename: str
    #: None cuando el hoster no informa tamaño hasta el momento de bajar.
    size: int | None = None
    alive: bool = True


@dataclass(frozen=True)
class CrawlResult:
    """Lo que hay detrás de un link: archivos, y links que aún hay que abrir."""

    files: list[CrawledFile] = field(default_factory=list)
    #: Links descubiertos que a su vez deben crawlearse (carpeta dentro de carpeta).
    children: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DirectLink:
    """URL descargable ya materializada, válida por poco tiempo."""

    url: str
    #: Cookies, referer o lo que esa URL exija para no devolver 403.
    headers: dict[str, str] = field(default_factory=dict)


class PluginError(Exception):
    """Raíz de todo fallo de plugin.

    Cada call site captura esta clase una sola vez. Si las variantes de abajo
    no compartieran raíz, agregar una nueva exigiría tocar cada call site y,
    mientras tanto, escaparía al loop.
    """


class LinkDead(PluginError):
    """El archivo ya no existe. No se reintenta: no va a revivir."""


class UnsupportedLink(PluginError):
    """Este plugin no sabe manejar esta URL; que siga probando el registro."""


class RateLimited(PluginError):
    """El hoster pide esperar. No es un fallo, es trabajo agendado."""

    #: Techo sobre lo que un plugin puede pedir esperar. Un valor absurdo
    #: (un bug de fecha, el año 9999) dejaría el item parado para siempre y no
    #: hay endpoint para reencolarlo a mano.
    MAX_WAIT = dt.timedelta(hours=6)

    def __init__(self, retry_at: dt.datetime, message: str = "rate limited"):
        super().__init__(message)
        if not isinstance(retry_at, dt.datetime):
            raise TypeError(f"retry_at debe ser datetime, no {type(retry_at).__name__}")

        # Normalizado a UTC naive, que es lo que guarda la columna y contra lo
        # que compara el scheduler. Sin esto, un plugin que use
        # datetime.now(UTC) - lo natural de escribir - se compara contra
        # utcnow() sin convertir, y en Postgres la columna ni siquiera acepta
        # un datetime con tzinfo.
        if retry_at.tzinfo is not None:
            retry_at = retry_at.astimezone(dt.timezone.utc).replace(tzinfo=None)

        now = dt.datetime.utcnow()
        self.retry_at = min(max(retry_at, now), now + self.MAX_WAIT)


@runtime_checkable
class Hoster(Protocol):
    """Las dos operaciones son distintas y ocurren en momentos distintos.

    `crawl` corre al agregar el link y descubre qué archivos hay detrás.
    `resolve` corre justo antes de descargar y devuelve la URL directa.

    Están separadas porque las URLs directas caducan: casi todo hoster las
    firma con un token de un solo uso o con TTL de minutos, así que resolver
    todo al agregar dejaría una cola de 40 archivos con 39 URLs vencidas
    antes de llegar a ellas.
    """

    name: str

    def can_handle(self, url: str) -> bool: ...

    async def crawl(self, url: str) -> CrawlResult: ...

    async def resolve(self, url: str) -> DirectLink: ...
