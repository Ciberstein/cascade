"""Descubre qué archivos hay detrás de un link. Sin DB: solo plugins."""

import logging
from dataclasses import dataclass

from app.plugins.base import LinkDead, PluginError
from app.plugins.registry import Registry, call_crawl, registry as default_registry

logger = logging.getLogger(__name__)

#: Cuán hondo se siguen carpetas dentro de carpetas. Bajo a propósito: un link
#: mal formado que se apunta a sí mismo es, sin tope, un bucle infinito.
MAX_DEPTH = 3


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
    pending: list[tuple[str, int]] = [(url, 0)]

    while pending:
        current, depth = pending.pop(0)
        if current in seen or depth > max_depth:
            continue
        seen.add(current)

        plugin = registry.find(current)
        try:
            result = await call_crawl(plugin, current)
        except LinkDead as exc:
            found.append(_failed(current, plugin.name, "dead", str(exc)))
            continue
        except PluginError as exc:
            found.append(_failed(current, plugin.name, "error", str(exc)))
            continue

        for discovered in result.files:
            found.append(
                DiscoveredFile(
                    url=discovered.url,
                    filename=discovered.filename,
                    size=discovered.size,
                    hoster=plugin.name,
                    status="ok" if discovered.alive else "dead",
                    error_message=None,
                )
            )

        pending.extend((child, depth + 1) for child in result.children)

    return found


def _failed(url: str, hoster: str, status: str, message: str) -> DiscoveredFile:
    return DiscoveredFile(
        url=url,
        filename=url.rstrip("/").rsplit("/", 1)[-1] or url,
        size=None,
        hoster=hoster,
        status=status,
        error_message=message,
    )
