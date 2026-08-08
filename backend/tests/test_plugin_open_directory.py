import pathlib

import httpx
import pytest

from app.plugins.base import LinkDead, UnsupportedLink
from app.plugins.open_directory import OpenDirectoryHoster

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "pages" / "nginx_autoindex.html"


def hoster_serving(body: str, status: int = 200, content_type: str = "text/html"):
    """Plugin cableado a una respuesta fija, sin tocar la red."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, headers={"Content-Type": content_type})

    return OpenDirectoryHoster(transport=httpx.MockTransport(handler))


def test_only_handles_urls_that_look_like_a_directory():
    plugin = OpenDirectoryHoster()
    assert plugin.can_handle("http://example.com/media/")
    assert not plugin.can_handle("http://example.com/media/ep01.mkv")


@pytest.mark.asyncio
async def test_crawl_lists_files_with_their_sizes():
    plugin = hoster_serving(FIXTURE.read_text())

    result = await plugin.crawl("http://example.com/media/")

    names = {f.filename: f for f in result.files}
    assert set(names) == {"ep01.mkv", "ep02.mkv", "notes.txt"}
    assert names["ep01.mkv"].url == "http://example.com/media/ep01.mkv"
    assert names["ep01.mkv"].size == 734003200


@pytest.mark.asyncio
async def test_crawl_reports_subdirectories_as_children_not_files():
    plugin = hoster_serving(FIXTURE.read_text())

    result = await plugin.crawl("http://example.com/media/")

    # El crawler los abre recursivamente; tratarlos como archivos encolaría
    # una descarga de una página HTML.
    assert result.children == ["http://example.com/media/subdir/"]


@pytest.mark.asyncio
async def test_crawl_ignores_the_parent_link():
    plugin = hoster_serving(FIXTURE.read_text())

    result = await plugin.crawl("http://example.com/media/")

    # "../" apunta hacia arriba: seguirlo saldría del árbol que el usuario
    # pidió y, con la recursión, podría volver a entrar por otro lado.
    assert all(not c.endswith("../") for c in result.children)


@pytest.mark.asyncio
async def test_a_missing_directory_is_dead_not_an_error():
    plugin = hoster_serving("not found", status=404)

    with pytest.raises(LinkDead):
        await plugin.crawl("http://example.com/gone/")


@pytest.mark.asyncio
async def test_a_non_html_response_is_not_ours():
    plugin = hoster_serving("{}", content_type="application/json")

    # Una URL con barra final que devuelve JSON es una API, no un autoindex.
    # Rechazarla deja que el registro caiga en direct en vez de inventar
    # archivos a partir de un cuerpo que no es una página.
    with pytest.raises(UnsupportedLink):
        await plugin.crawl("http://example.com/api/")


@pytest.mark.asyncio
async def test_resolve_returns_the_file_url_unchanged():
    plugin = OpenDirectoryHoster()
    link = await plugin.resolve("http://example.com/media/ep01.mkv")
    assert link.url == "http://example.com/media/ep01.mkv"
