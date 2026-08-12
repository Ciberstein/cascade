"""Plugin discovery and guarded execution."""

import asyncio
import importlib
import logging
import pkgutil

from app.plugins.base import DirectLink, CrawlResult, Hoster, PluginError

logger = logging.getLogger(__name__)

#: Ceiling per plugin call. Not against slow plugins (a hoster can legitimately
#: keep you waiting), but against hung ones: without a ceiling, a site that is
#: down holds a concurrency slot forever.
PLUGIN_TIMEOUT_SECONDS = 120.0

#: Goes last in the matching order: its can_handle returns True for everything.
_FALLBACK_NAME = "direct"


class Registry:
    def __init__(self, plugins: list[Hoster]):
        self._plugins = plugins

    def candidates(self, url: str) -> list[Hoster]:
        """Every plugin that accepts `url`, in order, with `direct` last.

        Returns the list rather than the first because a plugin can accept a URL
        and then discover it wasn't theirs (`UnsupportedLink`): the caller keeps
        trying until one answers, and `direct` closes the list.
        """
        accepted = []
        for plugin in self._plugins:
            try:
                if plugin.can_handle(url):
                    accepted.append(plugin)
            except Exception:  # noqa: BLE001 - third-party code, and outside the guard
                # can_handle is the first thing each plugin runs and the only
                # entry point that doesn't go through _guard. A bad regex here
                # would take down the whole search instead of dropping one
                # plugin.
                logger.exception("can_handle of %s failed on %s", plugin.name, url)
        return accepted

    def find(self, url: str) -> Hoster:
        candidates = self.candidates(url)
        if not candidates:
            raise PluginError(f"no plugin accepts {url}")  # impossible while direct exists
        return candidates[0]

    def get(self, name: str) -> Hoster | None:
        for plugin in self._plugins:
            if plugin.name == name:
                return plugin
        return None

    def names(self) -> list[str]:
        return [p.name for p in self._plugins]


def discover() -> list[Hoster]:
    """Loads every module under app.plugins that exposes PLUGIN.

    Adding a hoster means adding a file: there is no list to maintain, which is
    what makes fixing a broken plugin cheap.
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


async def call_resolve(
    plugin: Hoster,
    url: str,
    format_id: str | None = None,
    timeout: float = PLUGIN_TIMEOUT_SECONDS,
) -> DirectLink:
    return await _guard(plugin.resolve(url, format_id), plugin=plugin, url=url, timeout=timeout)


async def _guard(coro, *, plugin: Hoster, url: str, timeout: float):
    """Bounds the time and normalises any untyped failure into PluginError.

    Typed exceptions pass through untouched: the registry and the scheduler use
    them to decide what to do (keep trying, reschedule, mark dead), and
    wrapping them would lose that decision.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except PluginError:
        raise
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise PluginError(f"{plugin.name} timed out after {timeout}s on {url}") from exc
    except Exception as exc:  # noqa: BLE001 - third-party code inside the process
        logger.exception("plugin %s failed on %s", plugin.name, url)
        raise PluginError(f"{plugin.name}: {exc}") from exc


registry = Registry(discover())
