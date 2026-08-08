"""Pixeldrain, vía su API JSON pública.

Sirve de plantilla para hosters con API documentada: no hay HTML que parsear,
así que no se rompe cuando el sitio cambia su maquetado.
"""

import re

import httpx

from app.plugins.base import CrawledFile, CrawlResult, DirectLink, LinkDead, PluginError

_BASE = "https://pixeldrain.com"
_FILE_URL = re.compile(r"^https?://(?:www\.)?pixeldrain\.com/u/(?P<id>[\w-]+)")
_LIST_URL = re.compile(r"^https?://(?:www\.)?pixeldrain\.com/l/(?P<id>[\w-]+)")


class PixeldrainHoster:
    name = "pixeldrain"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def can_handle(self, url: str) -> bool:
        return bool(_FILE_URL.match(url) or _LIST_URL.match(url))

    async def crawl(self, url: str) -> CrawlResult:
        list_match = _LIST_URL.match(url)
        if list_match:
            body = await self._get(f"{_BASE}/api/list/{list_match.group('id')}", url)
            return CrawlResult(
                files=[
                    # Cada entrada apunta a su propia URL de archivo: el motor
                    # descarga archivos, no colecciones.
                    CrawledFile(
                        url=f"{_BASE}/u/{entry['id']}",
                        filename=entry.get("name", entry["id"]),
                        size=entry.get("size"),
                    )
                    for entry in body.get("files", [])
                ]
            )

        file_match = _FILE_URL.match(url)
        if file_match is None:
            raise PluginError(f"URL de pixeldrain no reconocida: {url}")

        body = await self._get(f"{_BASE}/api/file/{file_match.group('id')}/info", url)
        return CrawlResult(
            files=[
                CrawledFile(
                    url=url,
                    filename=body.get("name", file_match.group("id")),
                    size=body.get("size"),
                )
            ]
        )

    async def resolve(self, url: str) -> DirectLink:
        match = _FILE_URL.match(url)
        if match is None:
            raise PluginError(f"no se puede descargar directamente {url}")
        # /u/ es la página HTML; el binario vive en el endpoint de la API.
        return DirectLink(url=f"{_BASE}/api/file/{match.group('id')}?download")

    async def _get(self, api_url: str, original_url: str) -> dict:
        async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
            response = await client.get(api_url)

        if response.status_code in (404, 410):
            raise LinkDead(f"ya no existe: {original_url}")
        if response.status_code >= 400:
            raise PluginError(f"pixeldrain devolvió {response.status_code} para {original_url}")
        return response.json()


PLUGIN = PixeldrainHoster()
