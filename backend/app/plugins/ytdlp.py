"""Sitios de video, delegando en yt-dlp.

Cubre ~1750 sitios de una. La alternativa era escribir un extractor por sitio,
que es lo que hace JDownloader: no tiene sentido reescribir a mano algo que ya
existe, se mantiene solo y se rompe cada vez que un sitio cambia su reproductor.

Solo se ofrecen formatos **progresivos** por HTTP, es decir, un único archivo
que ya trae video y audio. Los formatos DASH/HLS vienen en pistas separadas o
troceados en segmentos, y ensamblarlos exige remuxear con ffmpeg - algo que el
motor de Cascade, que descarga un archivo por rangos, no sabe hacer. Antes que
entregar un video mudo o un .m3u8 inservible, se falla con un motivo claro.
"""

import asyncio
import logging
from typing import Any, Callable

from app.plugins.base import (
    CrawledFile,
    CrawlResult,
    DirectLink,
    LinkDead,
    PluginError,
    UnsupportedLink,
)

logger = logging.getLogger(__name__)

_YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": False,
    # Cinturón: en ningún caso yt-dlp debe escribir en disco. Quien descarga
    # es el motor de chunks, que es el que sabe reanudar y limitar velocidad.
    "skip_download": True,
}


class YtDlpHoster:
    name = "ytdlp"

    def __init__(self, extract: Callable[[str, bool], dict] | None = None):
        # Inyectable para poder testear sin red ni yt-dlp de por medio.
        self._extract = extract

    def can_handle(self, url: str) -> bool:
        """True si algún extractor específico reconoce la URL.

        Se excluye el extractor genérico a propósito: acepta cualquier cosa y,
        si contara, este plugin se quedaría con enlaces directos y carpetas que
        `direct` y `open_directory` manejan mejor.
        """
        if self._extract is not None:
            return True  # instancia de test: el guion decide

        try:
            from yt_dlp.extractor import gen_extractor_classes

            return any(
                ie.IE_NAME != "generic" and ie.suitable(url) for ie in gen_extractor_classes()
            )
        except Exception:  # noqa: BLE001 - can_handle nunca debe tumbar el registro
            logger.exception("no se pudo consultar los extractores de yt-dlp")
            return False

    async def crawl(self, url: str) -> CrawlResult:
        info = await self._info(url, flat=True)

        if info.get("_type") == "playlist":
            # Cada entrada es su propio archivo: el motor descarga archivos,
            # no colecciones. Sin tamaño, porque averiguarlo exigiría resolver
            # cada video de la lista y eso puede ser un centenar de requests.
            return CrawlResult(
                files=[
                    CrawledFile(
                        url=entry.get("url") or entry.get("webpage_url") or url,
                        filename=_filename_for(entry),
                    )
                    for entry in info.get("entries") or []
                    if entry
                ]
            )

        return CrawlResult(
            files=[
                CrawledFile(
                    url=info.get("webpage_url") or url,
                    filename=_filename_for(info),
                    size=_best_size(info),
                )
            ]
        )

    async def resolve(self, url: str) -> DirectLink:
        info = await self._info(url, flat=False)
        fmt = _pick_progressive(info.get("formats") or [])

        if fmt is None:
            raise PluginError(
                "este video solo se ofrece en pistas separadas o en segmentos "
                "(DASH/HLS); Cascade descarga un archivo por rangos y no puede "
                "remuxearlas"
            )

        # http_headers importa de verdad: los CDN de video suelen exigir el
        # Referer y el User-Agent con los que se pidió la página, y sin ellos
        # devuelven 403 aunque la URL sea correcta.
        return DirectLink(url=fmt["url"], headers=dict(fmt.get("http_headers") or {}))

    async def _info(self, url: str, flat: bool) -> dict[str, Any]:
        opts = dict(_YDL_OPTS)
        if flat:
            # Listar una playlist sin resolver cada video: la bandeja necesita
            # los títulos, no las URLs finales, que además caducan.
            opts["extract_flat"] = "in_playlist"

        # La traducción de errores envuelve también al extractor inyectado: es
        # justamente la parte que hay que poder probar, y dejarla fuera del
        # camino de test la volvería letra muerta.
        try:
            if self._extract is not None:
                return self._extract(url, flat)
            # yt-dlp es síncrono y hace I/O de red. Corriéndolo en el loop
            # bloquearía todo el proceso: el scheduler, el WebSocket de
            # progreso y la API entera, durante segundos por video.
            return await asyncio.to_thread(_extract_sync, url, opts)
        except Exception as exc:  # noqa: BLE001 - se traduce al vocabulario del contrato
            raise _translate(exc, url) from exc


def _extract_sync(url: str, opts: dict) -> dict[str, Any]:
    from yt_dlp import YoutubeDL

    with YoutubeDL(opts) as ydl:
        return ydl.sanitize_info(ydl.extract_info(url, download=False))


def _translate(exc: Exception, url: str) -> PluginError:
    """Traduce los errores de yt-dlp al vocabulario del contrato."""
    message = str(exc)
    lowered = message.lower()

    if any(s in lowered for s in ("not available", "private", "removed", "deleted", "404")):
        return LinkDead(f"{url}: {message}")
    if "unsupported url" in lowered:
        # Que siga probando el registro: termina en `direct`.
        return UnsupportedLink(f"{url}: {message}")
    return PluginError(f"{url}: {message}")


def _filename_for(info: dict[str, Any]) -> str:
    title = info.get("title") or info.get("id") or "video"
    ext = info.get("ext") or "mp4"
    return f"{title}.{ext}"


def _best_size(info: dict[str, Any]) -> int | None:
    fmt = _pick_progressive(info.get("formats") or [])
    if fmt is None:
        return None
    return fmt.get("filesize") or fmt.get("filesize_approx")


def _pick_progressive(formats: list[dict[str, Any]]) -> dict[str, Any] | None:
    """El mejor formato que sea un solo archivo HTTP con video y audio.

    Ojo con el vocabulario de yt-dlp, que distingue dos cosas que es fácil
    confundir: la cadena "none" significa que esa pista NO está, mientras que
    None significa que no se sabe. Facebook, por ejemplo, publica sus formatos
    progresivos ("sd" y "hd") sin declarar códecs: tratarlos como si les
    faltara el audio descartaría justo los únicos que sirven.

    Por eso van en dos tandas: primero los que declaran ambas pistas, y solo
    si no hay ninguno, los de códecs desconocidos. Lo explícitamente ausente
    ("none") nunca entra.
    """
    http = [
        (i, f)
        for i, f in enumerate(formats)
        if f.get("url") and str(f.get("protocol") or "").startswith("http")
    ]

    def usable(f: dict[str, Any], *, known: bool) -> bool:
        v, a = f.get("vcodec"), f.get("acodec")
        if v == "none" or a == "none":
            return False
        both_known = v is not None and a is not None
        return both_known if known else not both_known

    for known in (True, False):
        tier = [(i, f) for i, f in http if usable(f, known=known)]
        if tier:
            # El índice desempata: yt-dlp devuelve los formatos de peor a
            # mejor, así que ante altura y bitrate iguales - el caso de "sd" y
            # "hd", que no declaran ninguna de las dos - gana el último.
            return max(tier, key=lambda pair: (pair[1].get("height") or 0, pair[1].get("tbr") or 0, pair[0]))[1]
    return None


PLUGIN = YtDlpHoster()
