"""Índices de directorio abiertos (autoindex de nginx/Apache).

Es el caso más simple de "un link contiene N archivos", y sirve de plantilla
para cualquier plugin que expanda una carpeta.
"""

import re
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from app.plugins.base import CrawledFile, CrawlResult, DirectLink, LinkDead, UnsupportedLink

#: El autoindex de nginx pone el tamaño al final de la línea, después de la fecha.
_SIZE_AT_END_OF_LINE = re.compile(r"(\d+)\s*$")


class OpenDirectoryHoster:
    name = "open_directory"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        # Inyectable para poder testear contra páginas guardadas sin red.
        self._transport = transport

    def can_handle(self, url: str) -> bool:
        return urlparse(url).path.endswith("/")

    async def crawl(self, url: str) -> CrawlResult:
        async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
            response = await client.get(url)

        if response.status_code == 404:
            raise LinkDead(f"no existe: {url}")
        if response.status_code >= 400:
            raise UnsupportedLink(f"status {response.status_code} en {url}")
        if "html" not in response.headers.get("Content-Type", ""):
            raise UnsupportedLink(f"{url} no devuelve HTML")

        files: list[CrawledFile] = []
        children: list[str] = []

        for line in response.text.splitlines():
            node = HTMLParser(line).css_first("a")
            if node is None:
                continue
            href = node.attributes.get("href")
            if not href or href.startswith("?") or href.startswith("#"):
                continue

            absolute = urljoin(url, href)
            if not absolute.startswith(url):
                continue  # "../" y cualquier link que salga del árbol pedido

            if href.endswith("/"):
                children.append(absolute)
            else:
                files.append(
                    CrawledFile(
                        url=absolute,
                        filename=node.text().strip() or href,
                        size=_size_from(line),
                    )
                )

        return CrawlResult(files=files, children=children)

    async def resolve(self, url: str, format_id: str | None = None) -> DirectLink:
        # Un autoindex sirve el archivo en su propia URL: no hay nada que firmar.
        return DirectLink(url=url)


def _size_from(line: str) -> int | None:
    match = _SIZE_AT_END_OF_LINE.search(line.rstrip())
    return int(match.group(1)) if match else None


PLUGIN = OpenDirectoryHoster()
