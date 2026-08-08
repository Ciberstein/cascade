import json

import httpx
import pytest

from app.plugins.base import LinkDead
from app.plugins.pixeldrain import PixeldrainHoster


def hoster_with(routes: dict[str, tuple[int, dict]]):
    """routes: path -> (status, json body)."""

    def handler(request: httpx.Request) -> httpx.Response:
        status, body = routes.get(request.url.path, (404, {"success": False}))
        return httpx.Response(status, content=json.dumps(body), headers={"Content-Type": "application/json"})

    return PixeldrainHoster(transport=httpx.MockTransport(handler))


def test_handles_only_pixeldrain_urls():
    plugin = PixeldrainHoster()
    assert plugin.can_handle("https://pixeldrain.com/u/abc123")
    assert plugin.can_handle("https://pixeldrain.com/l/xyz789")
    assert not plugin.can_handle("https://example.com/u/abc123")


@pytest.mark.asyncio
async def test_crawl_of_a_single_file_reports_name_and_size():
    plugin = hoster_with({"/api/file/abc123/info": (200, {"name": "video.mkv", "size": 12345})})

    result = await plugin.crawl("https://pixeldrain.com/u/abc123")

    assert result.children == []
    assert len(result.files) == 1
    assert result.files[0].filename == "video.mkv"
    assert result.files[0].size == 12345
    assert result.files[0].url == "https://pixeldrain.com/u/abc123"


@pytest.mark.asyncio
async def test_crawl_of_an_album_expands_into_its_files():
    plugin = hoster_with(
        {
            "/api/list/xyz789": (
                200,
                {"files": [{"id": "f1", "name": "a.zip", "size": 10}, {"id": "f2", "name": "b.zip", "size": 20}]},
            )
        }
    )

    result = await plugin.crawl("https://pixeldrain.com/l/xyz789")

    assert [f.filename for f in result.files] == ["a.zip", "b.zip"]
    # Cada archivo apunta a su propia URL de archivo, no a la del álbum: el
    # motor descarga archivos, no colecciones.
    assert result.files[0].url == "https://pixeldrain.com/u/f1"


@pytest.mark.asyncio
async def test_a_deleted_file_is_dead():
    plugin = hoster_with({"/api/file/gone/info": (404, {"success": False, "message": "not found"})})

    with pytest.raises(LinkDead):
        await plugin.crawl("https://pixeldrain.com/u/gone")


@pytest.mark.asyncio
async def test_resolve_points_at_the_download_endpoint():
    plugin = PixeldrainHoster()

    link = await plugin.resolve("https://pixeldrain.com/u/abc123")

    # La página /u/ es HTML; el binario está en /api/file/{id}.
    assert link.url == "https://pixeldrain.com/api/file/abc123?download"
