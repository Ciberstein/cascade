"""Enlace directo: la URL pegada ya es descargable.

Existe como plugin en vez de como caso especial para que el resto del código
nunca tenga que ramificar entre "con plugin" y "sin plugin".
"""

from urllib.parse import urlparse

from app.plugins.base import CrawledFile, CrawlResult, DirectLink


def filename_from_url(url: str) -> str:
    """Último segmento del path de la URL, con "download" como último recurso.

    Se mira el path y no la URL entera: para "http://example.com/" la URL
    completa dejaría "example.com", es decir, guardaría el archivo con el
    nombre del host. Y se recortan las barras finales antes de partir porque,
    sin eso, toda URL terminada en "/" caería en "download" y dos carpetas
    distintas del mismo paquete se pisarían entre sí en el disco.
    """
    name = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
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
