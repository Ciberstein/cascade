"""Descubrimiento y ejecución protegida de plugins."""

import asyncio
import importlib
import logging
import pkgutil

from app.plugins.base import DirectLink, CrawlResult, Hoster, PluginError

logger = logging.getLogger(__name__)

#: Tope por llamada a un plugin. No es contra plugins lentos (un hoster puede
#: legítimamente hacerte esperar), es contra plugins colgados: sin tope, un
#: sitio caído retiene un slot de concurrencia para siempre.
PLUGIN_TIMEOUT_SECONDS = 120.0

#: Va último en el orden de matching: su can_handle devuelve True para todo.
_FALLBACK_NAME = "direct"


class Registry:
    def __init__(self, plugins: list[Hoster]):
        self._plugins = plugins

    def find(self, url: str) -> Hoster:
        for plugin in self._plugins:
            if plugin.can_handle(url):
                return plugin
        raise PluginError(f"ningún plugin acepta {url}")  # imposible con direct presente

    def get(self, name: str) -> Hoster | None:
        for plugin in self._plugins:
            if plugin.name == name:
                return plugin
        return None

    def names(self) -> list[str]:
        return [p.name for p in self._plugins]


def discover() -> list[Hoster]:
    """Carga todo módulo de app.plugins que exponga PLUGIN.

    Agregar un hoster es agregar un archivo: no hay lista que mantener, que es
    lo que hace barato arreglar un plugin roto.
    """
    import app.plugins as package

    found: list[Hoster] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        plugin = getattr(module, "PLUGIN", None)
        if plugin is not None:
            found.append(plugin)

    found.sort(key=lambda p: p.name == _FALLBACK_NAME)
    return found


async def call_crawl(plugin: Hoster, url: str, timeout: float = PLUGIN_TIMEOUT_SECONDS) -> CrawlResult:
    return await _guard(plugin.crawl(url), plugin=plugin, url=url, timeout=timeout)


async def call_resolve(plugin: Hoster, url: str, timeout: float = PLUGIN_TIMEOUT_SECONDS) -> DirectLink:
    return await _guard(plugin.resolve(url), plugin=plugin, url=url, timeout=timeout)


async def _guard(coro, *, plugin: Hoster, url: str, timeout: float):
    """Acota el tiempo y normaliza cualquier fallo no tipado a PluginError.

    Las excepciones tipadas pasan intactas: el registro y el scheduler las
    usan para decidir (seguir probando, reagendar, marcar muerto), y
    envolverlas perdería esa decisión.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except PluginError:
        raise
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise PluginError(f"{plugin.name} timed out after {timeout}s on {url}") from exc
    except Exception as exc:  # noqa: BLE001 - código de terceros dentro del proceso
        logger.exception("plugin %s failed on %s", plugin.name, url)
        raise PluginError(f"{plugin.name}: {exc}") from exc


registry = Registry(discover())
