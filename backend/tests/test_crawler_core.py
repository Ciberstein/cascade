import pytest

from app.crawler.core import MAX_DEPTH, DiscoveredFile, crawl_link
from app.plugins.base import CrawledFile, CrawlResult, LinkDead, PluginError
from app.plugins.registry import Registry


class ScriptedHoster:
    """Devuelve lo que el test le dicta para cada URL."""

    name = "scripted"

    def __init__(self, script: dict):
        self._script = script

    def can_handle(self, url):
        return url in self._script

    async def crawl(self, url):
        outcome = self._script[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def resolve(self, url, format_id=None):
        raise AssertionError("crawl_link no debe resolver")


class NeverHandles:
    name = "direct"

    def can_handle(self, url):
        return True

    async def crawl(self, url):
        return CrawlResult(files=[CrawledFile(url=url, filename="fallback.bin")])

    async def resolve(self, url, format_id=None):
        raise AssertionError("crawl_link no debe resolver")


@pytest.mark.asyncio
async def test_a_plain_link_yields_one_file():
    registry = Registry([NeverHandles()])

    found = await crawl_link("http://x/a.zip", registry=registry)

    assert found == [
        DiscoveredFile(
            url="http://x/a.zip", filename="fallback.bin", size=None, hoster="direct",
            status="ok", error_message=None,
        )
    ]


@pytest.mark.asyncio
async def test_children_are_followed_recursively():
    registry = Registry([
        ScriptedHoster({
            "http://x/dir/": CrawlResult(children=["http://x/dir/sub/"]),
            "http://x/dir/sub/": CrawlResult(files=[CrawledFile(url="http://x/dir/sub/a.zip", filename="a.zip", size=5)]),
        }),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/dir/", registry=registry)

    assert [f.filename for f in found] == ["a.zip"]
    assert found[0].size == 5


@pytest.mark.asyncio
async def test_recursion_stops_at_the_depth_limit():
    # Una carpeta que se apunta a sí misma. Sin tope esto no termina nunca y
    # se come el slot de crawl para siempre.
    registry = Registry([
        ScriptedHoster({"http://x/loop/": CrawlResult(children=["http://x/loop/"])}),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/loop/", registry=registry, max_depth=2)

    assert found == []


@pytest.mark.asyncio
async def test_a_url_already_seen_is_not_crawled_twice():
    calls = []

    class Counting(ScriptedHoster):
        async def crawl(self, url):
            calls.append(url)
            return await super().crawl(url)

    registry = Registry([
        Counting({
            "http://x/a/": CrawlResult(children=["http://x/b/", "http://x/b/"]),
            "http://x/b/": CrawlResult(files=[CrawledFile(url="http://x/b/f", filename="f")]),
        }),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/a/", registry=registry)

    assert calls.count("http://x/b/") == 1
    assert len(found) == 1


@pytest.mark.asyncio
async def test_a_dead_link_is_reported_not_raised():
    registry = Registry([
        ScriptedHoster({"http://x/gone": LinkDead("ya no está")}),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/gone", registry=registry)

    # Un link muerto dentro de una lista de 40 no puede tumbar el crawl entero:
    # se informa como resultado para que el usuario vea qué se perdió.
    assert len(found) == 1
    assert found[0].status == "dead"
    assert found[0].url == "http://x/gone"


@pytest.mark.asyncio
async def test_a_plugin_failure_is_reported_as_an_error_result():
    registry = Registry([
        ScriptedHoster({"http://x/boom": PluginError("el sitio cambió")}),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/boom", registry=registry)

    assert found[0].status == "error"
    assert found[0].error_message == "el sitio cambió"


@pytest.mark.asyncio
async def test_a_dead_file_inside_a_folder_is_kept_as_dead():
    registry = Registry([
        ScriptedHoster({
            "http://x/d/": CrawlResult(files=[
                CrawledFile(url="http://x/d/ok", filename="ok"),
                CrawledFile(url="http://x/d/no", filename="no", alive=False),
            ])
        }),
        NeverHandles(),
    ])

    found = await crawl_link("http://x/d/", registry=registry)

    assert {f.filename: f.status for f in found} == {"ok": "ok", "no": "dead"}


def test_the_default_depth_limit_is_small():
    assert MAX_DEPTH <= 5
