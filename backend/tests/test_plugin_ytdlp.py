"""Tests sin red: el extractor se inyecta con un guion."""

import pytest

from app.plugins.base import LinkDead, PluginError, UnsupportedLink
import app.plugins.ytdlp as ytdlp_mod
from app.plugins.ytdlp import parse_extractor_args, PLUGIN, YtDlpHoster

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
# Como los publica Facebook: un archivo único con video y audio, pero sin
# declarar códecs. None es "no se sabe", no "no está".
UNKNOWN_SD = {"format_id": "sd", "url": "https://cdn.example/sd.mp4", "protocol": "https",
              "vcodec": None, "acodec": None, "height": None}
UNKNOWN_HD = {**UNKNOWN_SD, "format_id": "hd", "url": "https://cdn.example/hd-unknown.mp4"}
AUDIO_ONLY = {"format_id": "a1", "url": "https://cdn.example/a.m4a", "protocol": "https",
              "vcodec": "none", "acodec": "mp4a", "height": None}


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
async def test_a_video_with_nothing_downloadable_fails_with_a_readable_reason():
    # Sin format_id se cae al mejor progresivo; si no hay ninguno, no hay nada
    # que entregar como archivo único.
    plugin = hoster({"formats": [VIDEO_ONLY, HLS]})

    with pytest.raises(PluginError, match="no quality downloadable"):
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


@pytest.mark.asyncio
async def test_a_format_with_unknown_codecs_is_usable_when_nothing_else_is():
    """El fallo real con un reel de Facebook.

    Facebook publica "sd" y "hd" sin declarar códecs, y el resto de sus
    formatos son pistas sueltas. Tratar None ("no se sabe") como si fuera
    "none" ("no está") descartaba justo los dos únicos descargables, y el
    video fallaba con un mensaje que decía que no había formato progresivo.
    """
    plugin = hoster({"formats": [AUDIO_ONLY, UNKNOWN_SD, VIDEO_ONLY, UNKNOWN_HD]})

    link = await plugin.resolve("https://sitio/v/1")

    # Entre dos de calidad indistinguible gana el último: yt-dlp los devuelve
    # de peor a mejor.
    assert link.url == "https://cdn.example/hd-unknown.mp4"


@pytest.mark.asyncio
async def test_a_declared_progressive_format_wins_over_an_unknown_one():
    plugin = hoster({"formats": [UNKNOWN_HD, PROGRESSIVE]})

    link = await plugin.resolve("https://sitio/v/1")

    # Si el sitio declaró ambas pistas, esa certeza vale más que adivinar.
    assert link.url == "https://cdn.example/v.mp4"


@pytest.mark.asyncio
async def test_a_track_explicitly_absent_is_never_picked():
    plugin = hoster({"formats": [AUDIO_ONLY, VIDEO_ONLY]})

    # "none" sí significa que la pista no está: eso daría un video mudo.
    with pytest.raises(PluginError, match="no quality downloadable"):
        await plugin.resolve("https://sitio/v/1")


def test_a_country_mirror_is_rewritten_to_the_canonical_domain():
    """Los espejos por país sirven lo mismo, pero yt-dlp registra solo el .com.

    Sin esto, pegar el enlace del espejo falla aunque el video sea
    perfectamente descargable - fue el caso que apareció probando con xnxx.es.
    """
    from app.plugins.ytdlp import canonical_url

    assert canonical_url("https://www.xnxx.es/video-abc/x") == "https://www.xnxx.com/video-abc/x"
    assert PLUGIN.can_handle("https://www.xnxx.es/video-abc/x")


def test_a_url_that_already_matches_is_left_untouched():
    from app.plugins.ytdlp import canonical_url

    url = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
    assert canonical_url(url) == url


def test_the_rewrite_preserves_the_path_and_the_query():
    from app.plugins.ytdlp import canonical_url

    result = canonical_url("https://www.xnxx.es/video-abc/titulo?x=1#frag")

    assert result == "https://www.xnxx.com/video-abc/titulo?x=1#frag"


def test_a_domain_nobody_handles_is_not_rewritten():
    """El reemplazo es auto-limitado: solo se aplica si el resultado matchea.

    Así no puede convertir una URL cualquiera en otra cosa - lo reescrito tiene
    que ser algo que yt-dlp ya sepa manejar.
    """
    from app.plugins.ytdlp import canonical_url

    for url in [
        "https://sitio-inventado.es/x",
        "https://ftp.debian.org/debian/doc/",
        "http://cascade-fs/media/",
    ]:
        assert canonical_url(url) == url
        assert not PLUGIN.can_handle(url)


def test_a_host_without_a_dot_is_left_alone():
    from app.plugins.ytdlp import canonical_url

    # Un servicio interno por nombre de contenedor no tiene TLD que cambiar.
    assert canonical_url("http://cascade-fs/media/") == "http://cascade-fs/media/"


def test_the_offered_qualities_go_from_best_to_worst():
    from app.plugins.ytdlp import _variants

    variants = _variants([PROGRESSIVE, PROGRESSIVE_HD, VIDEO_ONLY, {**PROGRESSIVE, "format_id": "a",
                          "vcodec": "none", "acodec": "mp4a", "height": None}])

    # Quien no elige espera la mejor, así que la primera tiene que serlo.
    assert [v.height for v in variants][:2] == [1080, 720]


def test_a_resolution_without_its_own_audio_is_offered_as_a_merge():
    from app.plugins.ytdlp import _variants

    audio = {"format_id": "251", "url": "https://cdn/a", "protocol": "https",
             "vcodec": "none", "acodec": "opus", "abr": 160}
    variants = _variants([VIDEO_ONLY, audio])

    # Sin esto, 1080p y todo lo de arriba quedaría fuera de alcance.
    assert variants[0].needs_merge
    assert variants[0].audio_format == "251"


def test_a_progressive_format_wins_over_a_merge_at_the_same_height():
    from app.plugins.ytdlp import _variants

    same_height_progressive = {**PROGRESSIVE, "format_id": "18", "height": 1080}
    audio = {"format_id": "251", "url": "https://cdn/a", "protocol": "https",
             "vcodec": "none", "acodec": "opus", "abr": 160}

    variants = _variants([VIDEO_ONLY, audio, same_height_progressive])

    # Unir cuesta una descarga extra y un paso de ffmpeg: solo se recurre a eso
    # cuando no hay un archivo único de esa calidad.
    assert not variants[0].needs_merge


def test_a_video_only_format_is_dropped_when_there_is_no_audio_to_pair():
    from app.plugins.ytdlp import _variants

    # Ofrecerlo daría un video mudo.
    assert _variants([VIDEO_ONLY]) == []


def test_the_audio_must_fit_the_video_container():
    """El fallo real con un short de YouTube.

    Elegir el audio por bitrate a secas emparejaba un video VP9 con audio AAC,
    y ffmpeg fallaba con "Only VP8 or VP9 or AV1 video and Vorbis or Opus audio
    are supported for WebM" - recién después de bajar las dos pistas enteras.
    """
    from app.plugins.ytdlp import _variants

    vp9 = {"format_id": "303", "url": "https://cdn/v", "protocol": "https", "ext": "webm",
           "vcodec": "vp09", "acodec": "none", "height": 1080}
    aac = {"format_id": "140", "url": "https://cdn/a1", "protocol": "https", "ext": "m4a",
           "vcodec": "none", "acodec": "mp4a", "abr": 128}
    opus = {"format_id": "251", "url": "https://cdn/a2", "protocol": "https", "ext": "webm",
            "vcodec": "none", "acodec": "opus", "abr": 100}

    variant = _variants([vp9, aac, opus])[0]

    # El AAC tiene más bitrate, pero no entra en un WebM.
    assert variant.audio_format == "251"
    assert variant.ext == "webm"


def test_an_mp4_video_gets_the_mp4_audio():
    from app.plugins.ytdlp import _variants

    h264 = {"format_id": "137", "url": "https://cdn/v", "protocol": "https", "ext": "mp4",
            "vcodec": "avc1", "acodec": "none", "height": 1080}
    aac = {"format_id": "140", "url": "https://cdn/a1", "protocol": "https", "ext": "m4a",
           "vcodec": "none", "acodec": "mp4a", "abr": 128}
    opus = {"format_id": "251", "url": "https://cdn/a2", "protocol": "https", "ext": "webm",
            "vcodec": "none", "acodec": "opus", "abr": 160}

    variant = _variants([h264, aac, opus])[0]

    # Opus tiene más bitrate, pero un MP4 no lo acepta.
    assert variant.audio_format == "140"
    assert variant.ext == "mp4"


def test_a_video_with_no_compatible_audio_is_not_offered():
    from app.plugins.ytdlp import _variants

    vp9 = {"format_id": "303", "url": "https://cdn/v", "protocol": "https", "ext": "webm",
           "vcodec": "vp09", "acodec": "none", "height": 1080}
    aac = {"format_id": "140", "url": "https://cdn/a", "protocol": "https", "ext": "m4a",
           "vcodec": "none", "acodec": "mp4a", "abr": 128}

    offered = _variants([vp9, aac])

    # Offering that pairing would download two tracks so ffmpeg could fail at
    # the end: AAC does not go inside a WebM.
    assert [v for v in offered if v.height is not None] == []
    # The audio on its own is a different matter - it needs no container it
    # cannot have, so it stays on the menu.
    assert [v.id for v in offered] == ["audio-140"]


def test_extractor_args_take_the_syntax_yt_dlp_documents():
    # The knob is turned by pasting what a yt-dlp issue thread says, so it has
    # to accept the CLI spelling rather than a shape of our own invention.
    assert parse_extractor_args("youtube:player_client=tv,web_safari") == {
        "youtube": {"player_client": ["tv", "web_safari"]}
    }
    assert parse_extractor_args("youtube:player_client=tv;formats=incomplete") == {
        "youtube": {"player_client": ["tv"], "formats": ["incomplete"]}
    }


def test_a_malformed_extractor_arg_is_ignored_rather_than_fatal():
    # It gets edited in a dashboard while something is already broken. A typo
    # there must not take the plugin down on top of whatever prompted it.
    for raw in ("", "   ", "youtube", "youtube:", ":player_client=tv", "nonsense"):
        assert parse_extractor_args(raw) == {}


def test_nothing_configured_leaves_yt_dlp_on_its_own_defaults():
    # Every site that isn't fighting us works untouched; the override only
    # exists for the ones that are.
    assert parse_extractor_args("") == {}


BOT_CHECK = "ERROR: [youtube] abc: Sign in to confirm you're not a bot. Use --cookies"


@pytest.mark.asyncio
async def test_a_block_moves_on_to_the_next_player_client():
    calls = []

    def flaky(url, flat):
        calls.append(url)
        if len(calls) < 3:
            raise RuntimeError(BOT_CHECK)
        return {"webpage_url": url, "title": "v", "ext": "mp4", "formats": []}

    result = await ytdlp_mod.YtDlpHoster(extract=flaky).crawl("https://youtube.com/watch?v=abc")

    # Being refused is not an answer, it is a closed door: try the next one.
    assert len(calls) == 3
    assert result.files[0].filename == "v.mp4"


@pytest.mark.asyncio
async def test_a_dead_video_is_not_retried_against_every_client():
    calls = []

    def gone(url, flat):
        calls.append(url)
        raise RuntimeError("ERROR: Video unavailable. This video has been removed")

    with pytest.raises(LinkDead):
        await ytdlp_mod.YtDlpHoster(extract=gone).crawl("https://youtube.com/watch?v=abc")

    # Retrying this reaches the same answer slower and hammers the site to do it.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_the_client_that_got_through_is_remembered(monkeypatch):
    monkeypatch.setattr(ytdlp_mod, "_working_client", None)
    calls = []

    def flaky(url, flat):
        calls.append(url)
        if len(calls) == 1:
            raise RuntimeError(BOT_CHECK)
        return {"webpage_url": url, "title": "v", "ext": "mp4", "formats": []}

    hoster = ytdlp_mod.YtDlpHoster(extract=flaky)
    await hoster.crawl("https://youtube.com/watch?v=abc")

    # The search cost is paid once; the next request starts where this ended.
    assert ytdlp_mod._working_client == ytdlp_mod._FALLBACK_CLIENTS[0]
    await hoster.crawl("https://youtube.com/watch?v=def")
    assert len(calls) == 3


def test_the_default_client_stays_near_the_front_after_a_fallback(monkeypatch):
    monkeypatch.setattr(ytdlp_mod, "_working_client", "tv")

    order = ytdlp_mod._client_order()

    # A block is usually temporary, and the default is the one the extractor is
    # written and tested against - so it keeps a place at the front.
    assert order[0] == "tv"
    assert order[1] is None
    assert len(order) == len(set(map(str, order)))


@pytest.mark.asyncio
async def test_being_blocked_everywhere_says_so_instead_of_echoing_yt_dlp(monkeypatch):
    monkeypatch.setattr(ytdlp_mod, "_working_client", None)

    def always_blocked(url, flat):
        raise RuntimeError(BOT_CHECK)

    with pytest.raises(PluginError) as caught:
        await ytdlp_mod.YtDlpHoster(extract=always_blocked).crawl("https://youtube.com/watch?v=a")

    # yt-dlp's raw complaint reads identically whether every client was tried or
    # none were, which left the one useful question answerable only from server
    # logs. The message now carries the answer.
    assert "blocked on all" in str(caught.value)
    assert "address is the problem" in str(caught.value)


def test_the_soundtrack_is_offered_on_its_own():
    from app.plugins.ytdlp import _variants

    progressive = {"format_id": "18", "url": "https://cdn/p", "protocol": "https", "ext": "mp4",
                   "vcodec": "avc1", "acodec": "mp4a", "height": 360}
    good_audio = {"format_id": "251", "url": "https://cdn/a2", "protocol": "https", "ext": "webm",
                  "vcodec": "none", "acodec": "opus", "abr": 160}
    poor_audio = {"format_id": "249", "url": "https://cdn/a1", "protocol": "https", "ext": "webm",
                  "vcodec": "none", "acodec": "opus", "abr": 50}

    offered = _variants([progressive, good_audio, poor_audio])

    # Last in the list: a different intent, not a lesser quality. Among the
    # resolutions it would read as "worse than 360p".
    audio = offered[-1]
    assert audio.label == "Audio only (mp3)"
    assert audio.video_format == "251"  # the best track, not the first found
    assert audio.ext == "mp3"
    assert audio.postprocess == "mp3"
    # No second track to fetch and nothing to merge: it is one small download.
    assert audio.needs_merge is False


def test_nothing_to_extract_offers_no_audio_option():
    from app.plugins.ytdlp import _variants

    progressive = {"format_id": "18", "url": "https://cdn/p", "protocol": "https", "ext": "mp4",
                   "vcodec": "avc1", "acodec": "mp4a", "height": 360}

    # Some sites publish only muxed files. Offering "audio only" there would
    # promise a small download and deliver the whole video.
    assert [v for v in _variants([progressive]) if v.postprocess] == []
