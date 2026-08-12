"""Discovers which files sit behind a link. No DB: plugins only."""

import logging
from collections import deque
from dataclasses import dataclass, field

from urllib.parse import urlparse

from app.paths import safe_filename
from app.plugins.base import CrawlResult, LinkDead, PluginError, UnsupportedLink
from app.plugins.registry import Registry, call_crawl, registry as default_registry

logger = logging.getLogger(__name__)

#: How deep folders inside folders are followed. Deliberately low: a malformed
#: link that points at itself is, without a ceiling, an infinite loop.
MAX_DEPTH = 3

#: Hard ceilings on the size of a crawl. Depth bounds how deep, not how much: a
#: distro mirror at depth 3 is hundreds of thousands of files, all held in
#: memory until they are written in one go. Without these limits a single link
#: can keep a crawl slot busy forever while the app looks healthy.
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
    variants: list = field(default_factory=list)


async def crawl_link(
    url: str,
    *,
    registry: Registry | None = None,
    max_depth: int = MAX_DEPTH,
) -> list[DiscoveredFile]:
    """Expands `url` into the concrete files it contains.

    Never raises because of one link: a dead one or a broken plugin comes back
    as a result carrying its status, because inside a list of 40 links one bad
    entry cannot take down the discovery of the other 39.
    """
    registry = registry or default_registry
    found: list[DiscoveredFile] = []
    seen: set[str] = set()
    # A deque and not a list: pop(0) on a list is O(n), and with a wide folder
    # the walk turns quadratic exactly when it is already struggling.
    pending: deque[tuple[str, int]] = deque([(url, 0)])

    while pending:
        if len(seen) >= MAX_LINKS_CRAWLED or len(found) >= MAX_FILES_FOUND:
            # Stop and leave a record: a silently partial list is worse than a
            # short list that says it was cut off.
            found.append(
                _failed(
                    url,
                    "direct",
                    "error",
                    f"crawl truncated: hit the ceiling of {MAX_LINKS_CRAWLED} links "
                    f"or {MAX_FILES_FOUND} files",
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
                    # Sanitised here, at the boundary: the filename usually
                    # comes from the text of a link in someone else's HTML, and
                    # later becomes a path on disk. Doing it at this single
                    # point covers every plugin, present and future.
                    filename=safe_filename(discovered.filename),
                    size=discovered.size,
                    hoster=plugin_name,
                    status="ok" if discovered.alive else "dead",
                    error_message=None,
                    variants=list(discovered.variants),
                )
            )

        pending.extend((child, depth + 1) for child in result.children)

    return found


async def _crawl_with_fallback(registry: Registry, url: str) -> tuple[str, "CrawlResult"]:
    """Tries every plugin that accepts the URL until one resolves it.

    `UnsupportedLink` means "it wasn't mine": the plugin accepted the URL by its
    shape and only discovered on fetching it that it didn't belong to it.
    Carrying on is what makes a folder returning 502, or a URL ending in "/"
    that actually serves a file, end up on `direct` instead of as a dead result.
    """
    candidates = registry.candidates(url)
    if not candidates:
        raise PluginError(f"no plugin accepts {url}")

    last: UnsupportedLink | None = None
    for plugin in candidates:
        try:
            return plugin.name, await call_crawl(plugin, url)
        except UnsupportedLink as exc:
            last = exc
            continue
    raise last if last is not None else PluginError(f"no plugin resolved {url}")


def _blamed(registry: Registry, url: str) -> str:
    """Which plugin gets recorded on a failed result."""
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
