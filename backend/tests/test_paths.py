"""El filename viene del HTML de un sitio ajeno: es entrada no confiable."""

import os

import pytest

from app.paths import ensure_within, safe_filename


@pytest.mark.parametrize(
    "hostile, expected",
    [
        ("../../../../etc/cron.d/pwned", "pwned"),
        ("/etc/cron.d/absolute", "absolute"),
        ("..", "download"),
        (".", "download"),
        ("", "download"),
        ("   ", "download"),
        ("subdir/notes.txt", "notes.txt"),
        # En Linux basename no trata "\" como separador, así que sin partir a
        # mano este nombre pasaría entero y volvería a ser peligroso cuando el
        # volumen se monta en Windows.
        (r"..\..\windows\system32\evil.exe", "evil.exe"),
    ],
)
def test_a_hostile_filename_cannot_escape_its_folder(hostile, expected):
    assert safe_filename(hostile) == expected


def test_an_ordinary_filename_survives_untouched():
    assert safe_filename("Episodio 01 [1080p].mkv") == "Episodio 01 [1080p].mkv"


def test_characters_illegal_on_windows_are_replaced_not_rejected():
    # Un nombre raro no debería impedir la descarga, solo dejar de ser peligroso.
    assert safe_filename('a:b*c?.bin') == "a_b_c_.bin"


def test_absurdly_long_names_are_truncated():
    assert len(safe_filename("x" * 5000)) <= 200


def test_truncation_keeps_the_extension():
    """El fallo real con un video de Facebook.

    El título del post pasaba los 200 caracteres, el recorte cortaba por el
    final y se llevaba puesto el ".mp4". El archivo quedaba sin extensión y el
    sistema operativo no sabía con qué abrirlo.
    """
    name = "t" * 400 + ".mp4"

    result = safe_filename(name)

    assert result.endswith(".mp4")
    assert len(result) <= 200


def test_a_title_full_of_dots_is_not_mistaken_for_an_extension():
    # Sin tope al largo del sufijo, "....una frase larguisima" pasaría por
    # extensión y el recorte conservaría basura en vez del nombre.
    name = "a" * 300 + ".esto no es una extension sino parte del titulo"

    result = safe_filename(name)

    assert len(result) <= 200


def test_a_long_name_without_any_extension_still_fits():
    assert len(safe_filename("z" * 400)) <= 200


def test_ensure_within_accepts_a_path_inside_the_package(tmp_path):
    inside = os.path.join(str(tmp_path), "a.bin")
    assert ensure_within(str(tmp_path), inside) == inside


def test_ensure_within_rejects_an_escape(tmp_path):
    # Segunda barrera: cubre cualquier ruta que llegue sin haber pasado por
    # safe_filename.
    outside = os.path.join(str(tmp_path), "..", "escaped.bin")
    with pytest.raises(ValueError):
        ensure_within(str(tmp_path), outside)


def test_ensure_within_is_not_fooled_by_a_sibling_with_the_same_prefix(tmp_path):
    base = os.path.join(str(tmp_path), "pkg")
    sibling = os.path.join(str(tmp_path), "pkg-evil", "a.bin")
    with pytest.raises(ValueError):
        ensure_within(base, sibling)


@pytest.mark.asyncio
async def test_a_hostile_link_text_cannot_escape_the_package(test_server, tmp_path):
    """El agujero que encontró la revisión final, extremo a extremo.

    open_directory tomaba el filename del TEXTO del enlace, no del href, y el
    href sí estaba validado. Un sitio que sirviera
    `<a href="ep01.mkv">/etc/cron.d/pwned</a>` conseguía que el motor creara
    ese directorio y escribiera bytes suyos ahí dentro.
    """
    import httpx

    from app.crawler.core import crawl_link
    from app.plugins.open_directory import OpenDirectoryHoster
    from app.plugins.registry import Registry
    from app.plugins.direct import PLUGIN as DIRECT

    page = (
        "<html><body><pre>"
        '<a href="ok.bin">ok.bin</a>\n'
        '<a href="a.bin">../../../../etc/cron.d/pwned</a>\n'
        '<a href="b.bin">/etc/cron.d/absolute</a>\n'
        "</pre></body></html>"
    )

    def handler(request):
        return httpx.Response(200, text=page, headers={"Content-Type": "text/html"})

    registry = Registry([OpenDirectoryHoster(transport=httpx.MockTransport(handler)), DIRECT])

    found = await crawl_link("http://example.com/media/", registry=registry)

    names = sorted(f.filename for f in found)
    assert names == ["absolute", "ok.bin", "pwned"]
    assert all("/" not in n and "\\" not in n and ".." not in n for n in names)
