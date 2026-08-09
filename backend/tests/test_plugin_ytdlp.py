"""Tests sin red: el extractor se inyecta con un guion."""

import pytest

from app.plugins.base import LinkDead, PluginError, UnsupportedLink
from app.plugins.ytdlp import PLUGIN, YtDlpHoster

PROGRESSIVE = {
    "format_id": "18",
    "url": "https://cdn.example/v.mp4",
    "protocol": "https",
    "vcodec": "avc1",
    "acodec": "mp4a",
    "height": 360,
    "filesize": 5_000_000,
    "http_headers": {"Referer": "https://sitio/video/1", "User-Agent": "Mozilla/5.0"},
}
PROGRESSIVE_HD = {**PROGRESSIVE, "format_id": "22", "url": "https://cdn.example/hd.mp4", "height": 720}
VIDEO_ONLY = {**PROGRESSIVE, "format_id": "137", "url": "https://cdn.example/vo.mp4", "acodec": "none", "height": 1080}
HLS = {**PROGRESSIVE, "format_id": "hls", "url": "https://cdn.example/x.m3u8", "protocol": "m3u8_native", "height": 1080}


def hoster(info=None, raises=None):
    def extract(url, flat):
        if raises is not None:
            raise raises
        return info

    return YtDlpHoster(extract=extract)


def test_the_shipped_plugin_recognizes_a_video_site():
    # can_handle real, sin red: solo consulta los extractores de yt-dlp.
    assert PLUGIN.can_handle("https://www.facebook.com/reel/1841942577217498")


def test_the_shipped_plugin_declines_what_other_plugins_handle_better():
    # El extractor genérico acepta cualquier cosa; si contara, este plugin se
    # quedaría con carpetas y enlaces directos que direct/open_directory
    # manejan mejor.
    assert not PLUGIN.can_handle("http://servidor/media/")
    assert not PLUGIN.can_handle("https://ftp.debian.org/debian/doc/")


@pytest.mark.asyncio
async def test_crawl_reports_the_video_with_its_title_and_size():
    plugin = hoster({"title": "Mi video", "ext": "mp4", "webpage_url": "https://sitio/v/1",
                     "formats": [PROGRESSIVE]})

    result = await plugin.crawl("https://sitio/v/1")

    assert len(result.files) == 1
    assert result.files[0].filename == "Mi video.mp4"
    assert result.files[0].size == 5_000_000
    # La URL guardada es la de la PÁGINA, no la del CDN: la del CDN caduca, y
    # resolve la vuelve a pedir justo antes de bajar.
    assert result.files[0].url == "https://sitio/v/1"


@pytest.mark.asyncio
async def test_a_playlist_expands_into_one_file_per_entry():
    plugin = hoster({
        "_type": "playlist",
        "entries": [
            {"title": "Uno", "ext": "mp4", "url": "https://sitio/v/1"},
            {"title": "Dos", "ext": "mp4", "url": "https://sitio/v/2"},
        ],
    })

    result = await plugin.crawl("https://sitio/lista")

    assert [f.filename for f in result.files] == ["Uno.mp4", "Dos.mp4"]
    assert result.files[1].url == "https://sitio/v/2"


@pytest.mark.asyncio
async def test_resolve_picks_the_best_progressive_format():
    plugin = hoster({"formats": [PROGRESSIVE, VIDEO_ONLY, HLS, PROGRESSIVE_HD]})

    link = await plugin.resolve("https://sitio/v/1")

    # 1080 existe pero es solo video, y el HLS viene en segmentos: el motor
    # descarga un archivo por rangos, no ensambla pistas.
    assert link.url == "https://cdn.example/hd.mp4"


@pytest.mark.asyncio
async def test_resolve_carries_the_headers_the_cdn_demands():
    plugin = hoster({"formats": [PROGRESSIVE]})

    link = await plugin.resolve("https://sitio/v/1")

    # Sin Referer y User-Agent, los CDN de video devuelven 403 aunque la URL
    # sea correcta.
    assert link.headers["Referer"] == "https://sitio/video/1"
    assert link.headers["User-Agent"] == "Mozilla/5.0"


@pytest.mark.asyncio
async def test_a_video_without_a_progressive_format_fails_with_a_readable_reason():
    plugin = hoster({"formats": [VIDEO_ONLY, HLS]})

    with pytest.raises(PluginError, match="DASH/HLS"):
        await plugin.resolve("https://sitio/v/1")


@pytest.mark.asyncio
async def test_a_removed_video_is_dead_not_an_error():
    plugin = hoster(raises=RuntimeError("Video unavailable. This video has been removed"))

    # Muerto no se reintenta; error sí puede reintentarse a mano. La distinción
    # es lo que evita reintentar para siempre algo que no va a volver.
    with pytest.raises(LinkDead):
        await plugin.crawl("https://sitio/v/borrado")


@pytest.mark.asyncio
async def test_an_unsupported_url_lets_the_registry_keep_trying():
    plugin = hoster(raises=RuntimeError("Unsupported URL: https://sitio/x"))

    with pytest.raises(UnsupportedLink):
        await plugin.crawl("https://sitio/x")


@pytest.mark.asyncio
async def test_any_other_failure_is_a_plain_plugin_error():
    plugin = hoster(raises=RuntimeError("el sitio cambió su reproductor"))

    with pytest.raises(PluginError) as caught:
        await plugin.crawl("https://sitio/v/1")
    assert not isinstance(caught.value, (LinkDead, UnsupportedLink))
