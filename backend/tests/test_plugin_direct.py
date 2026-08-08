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
    assert result.files[0].filename == "download"


@pytest.mark.asyncio
async def test_direct_resolve_returns_the_url_unchanged():
    link = await PLUGIN.resolve("http://example.com/a.zip")
    assert link.url == "http://example.com/a.zip"
    assert link.headers == {}
