"""Enlace directo: la URL pegada ya es descargable.

Existe como plugin en vez de como caso especial para que el resto del código
nunca tenga que ramificar entre "con plugin" y "sin plugin".
"""

from app.plugins.base import CrawledFile, CrawlResult, DirectLink


def filename_from_url(url: str) -> str:
    name = url.rsplit("/", 1)[-1]
    return name or "download"


class DirectHoster:
    name = "direct"

    def can_handle(self, url: str) -> bool:
        return True  # el registro lo consulta último, así que esto es el fallback

    async def crawl(self, url: str) -> CrawlResult:
        return CrawlResult(files=[CrawledFile(url=url, filename=filename_from_url(url))])

    async def resolve(self, url: str) -> DirectLink:
        return DirectLink(url=url)


PLUGIN = DirectHoster()
