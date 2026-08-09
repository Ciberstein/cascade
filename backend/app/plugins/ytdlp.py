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
from urllib.parse import urlsplit, urlunsplit

from app.plugins.base import (
    CrawledFile,
    Variant,
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
        return has_extractor(canonical_url(url))

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

        variants = _variants(info.get("formats") or [])
        return CrawlResult(
            files=[
                CrawledFile(
                    url=info.get("webpage_url") or url,
                    filename=_filename_for(info),
                    size=variants[0].size if variants else None,
                    variants=variants,
                )
            ]
        )

    async def resolve(self, url: str, format_id: str | None = None) -> DirectLink:
        info = await self._info(url, flat=False)
        formats = info.get("formats") or []

        if format_id is not None:
            # La calidad la eligió el usuario: se pide esa y no otra. Se busca
            # por id porque las URLs caducan y no se pueden guardar.
            fmt = next((f for f in formats if str(f.get("format_id")) == format_id), None)
            if fmt is None:
                raise PluginError(
                    f"el formato {format_id} ya no está disponible para este video"
                )
        else:
            fmt = _pick_progressive(formats)

        if fmt is None:
            raise PluginError(
                "este video no ofrece ninguna calidad descargable como archivo único"
            )

        # http_headers importa de verdad: los CDN de video suelen exigir el
        # Referer y el User-Agent con los que se pidió la página, y sin ellos
        # devuelven 403 aunque la URL sea correcta.
        return DirectLink(url=fmt["url"], headers=dict(fmt.get("http_headers") or {}))

    async def _info(self, url: str, flat: bool) -> dict[str, Any]:
        # Canonicalizado acá, en un solo punto: crawl y resolve tienen que
        # coincidir, o el crawl encontraría el video y la descarga fallaría.
        url = canonical_url(url) if self._extract is None else url

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


def has_extractor(url: str) -> bool:
    """Si algún extractor específico de yt-dlp reconoce esta URL."""
    try:
        from yt_dlp.extractor import gen_extractor_classes

        return any(ie.IE_NAME != "generic" and ie.suitable(url) for ie in gen_extractor_classes())
    except Exception:  # noqa: BLE001 - esto corre dentro de can_handle, que no puede tumbar el registro
        logger.exception("no se pudo consultar los extractores de yt-dlp")
        return False


def canonical_url(url: str) -> str:
    """Reemplaza el TLD por .com si eso hace que un extractor reconozca la URL.

    Muchos sitios tienen espejos por país - xnxx.es junto a xnxx.com - que
    sirven el mismo contenido con la misma estructura de URL, pero yt-dlp
    registra solo el dominio canónico. Sin esto, pegar el enlace del espejo
    falla aunque el video sea perfectamente descargable.

    El cambio es deliberadamente conservador: solo se aplica cuando la URL
    original NO matchea y la reescrita SÍ. Eso lo vuelve auto-limitado - no
    puede convertir una URL en cualquier otra cosa, porque el resultado tiene
    que ser algo que yt-dlp ya sepa manejar.
    """
    if has_extractor(url):
        return url

    parsed = urlsplit(url)
    host = parsed.hostname
    if not host or host.endswith(".com") or "." not in host:
        return url

    swapped_host = f"{host.rsplit('.', 1)[0]}.com"
    netloc = f"{swapped_host}:{parsed.port}" if parsed.port else swapped_host
    candidate = urlunsplit(parsed._replace(netloc=netloc))

    return candidate if has_extractor(candidate) else url


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


#: Las alturas que se ofrecen. Listar las 33 variantes que publica YouTube
#: sería una pared de opciones donde casi todas son indistinguibles.
_OFFERED_HEIGHTS = (2160, 1440, 1080, 720, 480, 360, 240)


def _variants(formats: list[dict[str, Any]]) -> list[Variant]:
    """Las calidades entre las que el usuario puede elegir, de mejor a peor.

    Incluye las que vienen en pistas separadas: se emparejan con el mejor audio
    suelto y el motor las une al terminar. Sin eso, en YouTube la única opción
    sería 360p - la única progresiva de las 33 que publica - para un video que
    existe en 4K.

    Ante dos formatos de la misma altura gana el progresivo: unir cuesta una
    descarga extra y un paso de ffmpeg, así que solo se recurre a eso cuando no
    hay un archivo único de esa calidad.
    """
    http = [
        f for f in formats
        if f.get("url") and str(f.get("protocol") or "").startswith("http")
    ]
    best_audio = _best_audio(http)

    candidates: dict[object, Variant] = {}
    for fmt in http:
        if fmt.get("vcodec") == "none":
            continue  # audio suelto: no es una calidad elegible por sí misma

        # "none" es que la pista no está; None es que no se sabe. Tratar el
        # desconocido como ausente marcaría para unir formatos que ya traen
        # audio - los "sd"/"hd" de Facebook son justamente así.
        needs_audio = fmt.get("acodec") == "none"
        audio_format = str(best_audio["format_id"]) if (needs_audio and best_audio) else None
        if needs_audio and audio_format is None:
            continue  # no hay audio con qué completarlo: no se puede entregar

        size = (fmt.get("filesize") or fmt.get("filesize_approx") or 0)
        if audio_format:
            size += (best_audio or {}).get("filesize") or (best_audio or {}).get("filesize_approx") or 0

        height = fmt.get("height")
        variant = Variant(
            id=str(fmt["format_id"]),
            label=f"{height}p" if height else str(fmt.get("format_id")),
            video_format=str(fmt["format_id"]),
            audio_format=audio_format,
            height=height,
            size=size or None,
        )

        key = height if height is not None else str(fmt.get("format_id"))
        if height is not None and height not in _OFFERED_HEIGHTS:
            continue
        previo = candidates.get(key)
        if previo is None or (previo.needs_merge and not variant.needs_merge):
            candidates[key] = variant

    con_altura = [candidates[h] for h in _OFFERED_HEIGHTS if h in candidates]
    # Los sin altura declarada (Facebook publica "sd"/"hd" así) van después, en
    # el orden inverso al de yt-dlp, que los da de peor a mejor.
    sin_altura = [v for k, v in candidates.items() if not isinstance(k, int)]
    return con_altura + list(reversed(sin_altura))


def _best_audio(formats: list[dict[str, Any]]) -> dict[str, Any] | None:
    audio = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("vcodec") == "none"]
    if not audio:
        return None
    return max(audio, key=lambda f: f.get("abr") or f.get("tbr") or 0)
