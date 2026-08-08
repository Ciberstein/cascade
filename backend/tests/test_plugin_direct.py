import pytest

from app.plugins.direct import PLUGIN


def test_direct_handles_any_url():
    # Es la red de seguridad del registro: si no matchea nadie más, matchea este.
    assert PLUGIN.can_handle("http://example.com/a.zip")
    assert PLUGIN.can_handle("https://whatever/x")


@pytest.mark.asyncio
async def test_direct_crawl_reports_the_url_as_a_single_file():
    result = await PLUGIN.crawl("http://example.com/path/a.zip")

    assert result.children == []
    assert len(result.files) == 1
    assert result.files[0].url == "http://example.com/path/a.zip"
    assert result.files[0].filename == "a.zip"
    # El tamaño lo averigua el probe HEAD del motor, no este plugin: hacer
    # una request extra acá duplicaría la que el downloader ya hace igual.
    assert result.files[0].size is None


@pytest.mark.asyncio
async def test_direct_crawl_falls_back_to_a_usable_filename():
    result = await PLUGIN.crawl("http://example.com/")
    # No "example.com": guardar el archivo con el nombre del host sería peor
    # que un nombre genérico.
    assert result.files[0].filename == "download"


@pytest.mark.asyncio
async def test_two_trailing_slash_urls_do_not_collapse_to_the_same_name():
    a = await PLUGIN.crawl("http://x/files/")
    b = await PLUGIN.crawl("http://x/other/")

    # Ambos van a la misma carpeta del paquete: si los dos se llamaran
    # "download", el segundo pisaría al primero en el disco sin aviso.
    assert a.files[0].filename == "files"
    assert b.files[0].filename == "other"


@pytest.mark.asyncio
async def test_direct_resolve_returns_the_url_unchanged():
    link = await PLUGIN.resolve("http://example.com/a.zip")
    assert link.url == "http://example.com/a.zip"
    assert link.headers == {}
