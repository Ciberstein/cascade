"""Video sites, delegating to yt-dlp.

Covers ~1750 sites in one go. The alternative was writing an extractor per
site, which is what JDownloader does: there is no sense in hand-rewriting
something that already exists, maintains itself, and breaks every time a site
changes its player.

Only formats served over plain HTTP are offered - a single progressive file, or
a video track plus an audio track that the engine merges with ffmpeg once both
have been downloaded (see app/engine/merge.py). Segmented HLS is left out: the
Cascade engine downloads a file by byte ranges and cannot assemble a playlist.
Rather than hand over a silent video or a useless .m3u8, it fails with a clear
reason.
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
    # Belt and braces: under no circumstances should yt-dlp write to disk. The
    # chunk engine does the downloading - it is the one that knows how to
    # resume and to throttle.
    "skip_download": True,
}


class YtDlpHoster:
    name = "ytdlp"

    def __init__(self, extract: Callable[[str, bool], dict] | None = None):
        # Inyectable para poder testear sin red ni yt-dlp de por medio.
        self._extract = extract

    def can_handle(self, url: str) -> bool:
        """True if some specific extractor recognises the URL.

        The generic extractor is excluded on purpose: it accepts anything and,
        if it counted, this plugin would swallow plain links and folders that
        `direct` and `open_directory` handle better.
        """
        if self._extract is not None:
            return True  # instancia de test: el guion decide
        return has_extractor(canonical_url(url))

    async def crawl(self, url: str) -> CrawlResult:
        info = await self._info(url, flat=True)

        if info.get("_type") == "playlist":
            # Each entry is its own file: the engine downloads files, not
            # collections. No size, because finding out would mean resolving
            # every video in the list - potentially a hundred requests.
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
            # The user chose the quality: ask for that one and no other. It
            # is looked up by id because URLs expire and cannot be stored.
            fmt = next((f for f in formats if str(f.get("format_id")) == format_id), None)
            if fmt is None:
                raise PluginError(
                    f"format {format_id} is no longer available for this video"
                )
        else:
            fmt = _pick_progressive(formats)

        if fmt is None:
            raise PluginError(
                "this video offers no quality downloadable as a single file"
            )

        # http_headers genuinely matters: video CDNs usually demand the
        # Referer and User-Agent the page was requested with, and without them
        # they answer 403 even when the URL is right.
        return DirectLink(url=fmt["url"], headers=dict(fmt.get("http_headers") or {}))

    async def _info(self, url: str, flat: bool) -> dict[str, Any]:
        # Canonicalised here, at a single point: crawl and resolve have to
        # agree, or the crawl would find the video and the download would fail.
        url = canonical_url(url) if self._extract is None else url

        opts = dict(_YDL_OPTS)
        if flat:
            # List a playlist without resolving each video: the tray needs the
            # titles, not the final URLs, which expire anyway.
            opts["extract_flat"] = "in_playlist"

        # The error translation wraps the injected extractor too: that is
        # precisely the part that has to be testable, and leaving it outside the
        # test path would make it dead letter.
        try:
            if self._extract is not None:
                return self._extract(url, flat)
            # yt-dlp is synchronous and does network I/O. Running it on the
            # loop would block the whole process: the scheduler, the progress
            # WebSocket and the entire API, for seconds per video.
            return await asyncio.to_thread(_extract_sync, url, opts)
        except Exception as exc:  # noqa: BLE001 - se traduce al vocabulario del contrato
            raise _translate(exc, url) from exc


def has_extractor(url: str) -> bool:
    """Whether some specific yt-dlp extractor recognises this URL."""
    try:
        from yt_dlp.extractor import gen_extractor_classes

        return any(ie.IE_NAME != "generic" and ie.suitable(url) for ie in gen_extractor_classes())
    except Exception:  # noqa: BLE001 - esto corre dentro de can_handle, que no puede tumbar el registro
        logger.exception("no se pudo consultar los extractores de yt-dlp")
        return False


def canonical_url(url: str) -> str:
    """Swaps the TLD for .com when that makes an extractor recognise the URL.

    Many sites run country mirrors - xnxx.es alongside xnxx.com - serving the
    same content with the same URL structure, but yt-dlp only registers the
    canonical domain. Without this, pasting the mirror's link fails even though
    the video is perfectly downloadable.

    The change is deliberately conservative: it only applies when the original
    URL does NOT match and the rewritten one does. That makes it self-limiting -
    it cannot turn a URL into just anything, because the result has to be
    something yt-dlp already knows how to handle.
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
    """The best format that is a single HTTP file carrying video and audio.

    Mind yt-dlp's vocabulary, which distinguishes two things that are easy to
    confuse: the string "none" means that track is NOT there, while None means
    it is unknown. Facebook, for instance, publishes its progressive formats
    ("sd" and "hd") without declaring codecs: treating them as missing audio
    would discard precisely the only usable ones.

    Hence two passes: first those declaring both tracks, and only if there are
    none, those with unknown codecs. What is explicitly absent ("none") never
    qualifies.
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
            # The index breaks ties: yt-dlp returns formats worst to best, so
            # with equal height and bitrate - the case of "sd" and "hd", which
            # declare neither - the last one wins.
            return max(tier, key=lambda pair: (pair[1].get("height") or 0, pair[1].get("tbr") or 0, pair[0]))[1]
    return None


PLUGIN = YtDlpHoster()


#: The heights on offer. Listing the 33 variants YouTube publishes would be a
#: wall of options where almost all are indistinguishable.
_OFFERED_HEIGHTS = (2160, 1440, 1080, 720, 480, 360, 240)


def _variants(formats: list[dict[str, Any]]) -> list[Variant]:
    """Las calidades entre las que el usuario puede elegir, de mejor a peor.

    Includes those arriving as separate tracks: they are paired with the best
    loose audio and the engine merges them at the end. Without that, YouTube's
    only option would be 360p - the single progressive one of the 33 it
    publishes - for a video that exists in 4K.

    Between two formats of the same height the progressive one wins: merging
    costs an extra download and an ffmpeg pass, so it is only used when there
    is no single file at that quality.
    """
    http = [
        f for f in formats
        if f.get("url") and str(f.get("protocol") or "").startswith("http")
    ]
    audios = [f for f in http if f.get("acodec") not in (None, "none") and f.get("vcodec") == "none"]

    candidates: dict[object, Variant] = {}
    for fmt in http:
        if fmt.get("vcodec") == "none":
            continue  # loose audio: not a quality anyone can pick on its own

        # "none" means the track is absent; None means unknown. Treating the
        # unknown as absent would mark for merging formats that already carry
        # audio - Facebook's "sd"/"hd" are exactly that.
        needs_audio = fmt.get("acodec") == "none"
        audio = _audio_for(fmt, audios) if needs_audio else None
        if needs_audio and audio is None:
            continue  # no compatible audio to complete it with

        audio_format = str(audio["format_id"]) if audio else None

        size = (fmt.get("filesize") or fmt.get("filesize_approx") or 0)
        if audio:
            size += audio.get("filesize") or audio.get("filesize_approx") or 0

        height = fmt.get("height")
        variant = Variant(
            id=str(fmt["format_id"]),
            label=f"{height}p" if height else str(fmt.get("format_id")),
            video_format=str(fmt["format_id"]),
            audio_format=audio_format,
            height=height,
            size=size or None,
            ext=fmt.get("ext"),
        )

        key = height if height is not None else str(fmt.get("format_id"))
        if height is not None and height not in _OFFERED_HEIGHTS:
            continue
        previo = candidates.get(key)
        if previo is None or (previo.needs_merge and not variant.needs_merge):
            candidates[key] = variant

    with_height = [candidates[h] for h in _OFFERED_HEIGHTS if h in candidates]
    # Those with no declared height (Facebook publishes "sd"/"hd" that way) go
    # afterwards, in reverse of yt-dlp's order, which runs worst to best.
    without_height = [v for k, v in candidates.items() if not isinstance(k, int)]
    return with_height + list(reversed(without_height))


#: Which audio can share a container with which video. Putting AAC in a WebM,
#: or VP9 in an MP4, is not a preference: the container rejects it and ffmpeg
#: writes nothing.
_COMPATIBLE_AUDIO_EXT = {"webm": {"webm", "opus"}, "mp4": {"m4a", "mp4"}, "m4a": {"m4a", "mp4"}}


def _audio_for(video: dict[str, Any], audios: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The best audio the video's container will accept.

    Choosing on bitrate alone broke the merge: for a VP9 video it picked the
    AAC, and "Only VP8 or VP9 or AV1 video and Vorbis or Opus audio are
    supported for WebM" failed ffmpeg after both tracks had been downloaded in
    full.
    """
    allowed = _COMPATIBLE_AUDIO_EXT.get(str(video.get("ext") or "").lower())
    usable = [a for a in audios if allowed is None or str(a.get("ext") or "").lower() in allowed]
    if not usable:
        return None
    return max(usable, key=lambda f: f.get("abr") or f.get("tbr") or 0)
