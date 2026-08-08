"""Descubre qué archivos hay detrás de un link. Sin DB: solo plugins."""

import logging
from collections import deque
from dataclasses import dataclass

from urllib.parse import urlparse

from app.paths import safe_filename
from app.plugins.base import CrawlResult, LinkDead, PluginError, UnsupportedLink
from app.plugins.registry import Registry, call_crawl, registry as default_registry

logger = logging.getLogger(__name__)

#: Cuán hondo se siguen carpetas dentro de carpetas. Bajo a propósito: un link
#: mal formado que se apunta a sí mismo es, sin tope, un bucle infinito.
MAX_DEPTH = 3

#: Techos duros sobre el tamaño del crawl. La profundidad acota cuán hondo,
#: no cuánto: un mirror de una distro a profundidad 3 son cientos de miles de
#: archivos, y todos se retienen en memoria hasta escribirlos de una sola vez.
#: Sin estos topes un solo link puede dejar un slot de crawl trabajando para
#: siempre mientras la app aparenta estar sana.
MAX_LINKS_CRAWLED = 500
MAX_FILES_FOUND = 5000


@dataclass(frozen=True)
class DiscoveredFile:
    url: str
    filename: str
    size: int | None
    hoster: str
    status: str  # "ok" | "dead" | "error"
    error_message: str | None


async def crawl_link(
    url: str,
    *,
    registry: Registry | None = None,
    max_depth: int = MAX_DEPTH,
) -> list[DiscoveredFile]:
    """Expande `url` en los archivos concretos que contiene.

    Nunca lanza por culpa de un link: un muerto o un plugin roto se devuelven
    como resultados con su estado, porque dentro de una lista de 40 links uno
    malo no puede tumbar el descubrimiento de los otros 39.
    """
    registry = registry or default_registry
    found: list[DiscoveredFile] = []
    seen: set[str] = set()
    # deque y no list: pop(0) sobre una lista es O(n), y con una carpeta ancha
    # el recorrido pasa a ser cuadrático justo cuando ya está sufriendo.
    pending: deque[tuple[str, int]] = deque([(url, 0)])

    while pending:
        if len(seen) >= MAX_LINKS_CRAWLED or len(found) >= MAX_FILES_FOUND:
            # Se corta y se deja constancia: una lista silenciosamente parcial
            # es peor que una lista corta que dice que está cortada.
            found.append(
                _failed(
                    url,
                    "direct",
                    "error",
                    f"crawl truncado: se alcanzó el tope de {MAX_LINKS_CRAWLED} enlaces "
                    f"o {MAX_FILES_FOUND} archivos",
                )
            )
            break

        current, depth = pending.popleft()
        if current in seen or depth > max_depth:
            continue
        seen.add(current)

        try:
            plugin_name, result = await _crawl_with_fallback(registry, current)
        except LinkDead as exc:
            found.append(_failed(current, _blamed(registry, current), "dead", str(exc)))
            continue
        except PluginError as exc:
            found.append(_failed(current, _blamed(registry, current), "error", str(exc)))
            continue

        for discovered in result.files:
            found.append(
                DiscoveredFile(
                    url=discovered.url,
                    # Saneado acá, en el borde: el filename suele salir del
                    # texto de un enlace en HTML ajeno, y más adelante se
                    # convierte en una ruta en disco. Hacerlo en este único
                    # punto cubre a todos los plugins, presentes y futuros.
                    filename=safe_filename(discovered.filename),
                    size=discovered.size,
                    hoster=plugin_name,
                    status="ok" if discovered.alive else "dead",
                    error_message=None,
                )
            )

        pending.extend((child, depth + 1) for child in result.children)

    return found


async def _crawl_with_fallback(registry: Registry, url: str) -> tuple[str, "CrawlResult"]:
    """Prueba cada plugin que acepte la URL hasta que uno la resuelva.

    `UnsupportedLink` significa "no era mía": el plugin aceptó la URL por su
    forma y recién al pedirla descubrió que no le correspondía. Seguir
    probando es lo que hace que una carpeta que devuelve 502, o una URL
    terminada en "/" que en realidad sirve un archivo, termine en `direct` en
    vez de quedar como un resultado muerto.
    """
    candidates = registry.candidates(url)
    if not candidates:
        raise PluginError(f"ningún plugin acepta {url}")

    last: UnsupportedLink | None = None
    for plugin in candidates:
        try:
            return plugin.name, await call_crawl(plugin, url)
        except UnsupportedLink as exc:
            last = exc
            continue
    raise last if last is not None else PluginError(f"ningún plugin resolvió {url}")


def _blamed(registry: Registry, url: str) -> str:
    """Qué plugin se anota en un resultado fallido."""
    candidates = registry.candidates(url)
    return candidates[0].name if candidates else "direct"


def _failed(url: str, hoster: str, status: str, message: str) -> DiscoveredFile:
    return DiscoveredFile(
        url=url,
        filename=safe_filename(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]),
        size=None,
        hoster=hoster,
        status=status,
        error_message=message,
    )
