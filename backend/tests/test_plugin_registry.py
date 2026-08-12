import asyncio

import pytest

from app.plugins.base import CrawlResult, DirectLink, PluginError, UnsupportedLink
from app.plugins.registry import (
    PLUGIN_TIMEOUT_SECONDS,
    Registry,
    call_crawl,
    call_resolve,
    discover,
)


class FakeHoster:
    def __init__(self, name, prefix, crawl_impl=None, resolve_impl=None):
        self.name = name
        self._prefix = prefix
        self._crawl_impl = crawl_impl
        self._resolve_impl = resolve_impl

    def can_handle(self, url):
        return url.startswith(self._prefix)

    async def crawl(self, url):
        if self._crawl_impl:
            return await self._crawl_impl(url)
        return CrawlResult()

    async def resolve(self, url, format_id=None):
        if self._resolve_impl:
            return await self._resolve_impl(url)
        return DirectLink(url=url)


def test_discovery_finds_the_shipped_plugins():
    names = {p.name for p in discover()}
    assert {"direct", "open_directory", "pixeldrain"} <= names


def test_direct_is_always_last_so_it_never_shadows_a_real_hoster():
    # can_handle de direct devuelve True para todo. Si quedara primero, ningún
    # otro plugin se usaría jamás.
    assert discover()[-1].name == "direct"


def test_find_returns_the_first_matching_plugin():
    a = FakeHoster("a", "http://a/")
    fallback = FakeHoster("direct", "")
    registry = Registry([a, fallback])

    assert registry.find("http://a/x").name == "a"
    assert registry.find("http://zzz/x").name == "direct"


def test_get_looks_a_plugin_up_by_name():
    a = FakeHoster("a", "http://a/")
    registry = Registry([a])

    assert registry.get("a") is a
    assert registry.get("nope") is None


@pytest.mark.asyncio
async def test_a_hung_plugin_does_not_hold_its_slot_forever():
    async def never_returns(url):
        await asyncio.sleep(3600)

    plugin = FakeHoster("slow", "http://", crawl_impl=never_returns)

    # Sin timeout, unos pocos links contra un sitio caído congelan toda la cola:
    # cada uno retiene un slot de concurrencia de forma indefinida.
    with pytest.raises(PluginError, match="timed out"):
        await call_crawl(plugin, "http://x/a", timeout=0.05)


@pytest.mark.asyncio
async def test_an_unexpected_exception_is_normalized_to_plugin_error():
    async def explodes(url):
        raise ValueError("el sitio devolvió algo que no esperaba")

    plugin = FakeHoster("boom", "http://", crawl_impl=explodes)

    # Un plugin es código de terceros dentro del proceso. Dejar escapar una
    # excepción arbitraria mata el loop que lo llamó.
    with pytest.raises(PluginError, match="el sitio devolvió algo"):
        await call_crawl(plugin, "http://x/a")


@pytest.mark.asyncio
async def test_typed_plugin_errors_pass_through_unchanged():
    async def unsupported(url):
        raise UnsupportedLink("no es mío")

    plugin = FakeHoster("picky", "http://", crawl_impl=unsupported)

    # El registro las usa para decidir; envolverlas en PluginError perdería
    # esa información y un link soportado terminaría como error.
    with pytest.raises(UnsupportedLink):
        await call_crawl(plugin, "http://x/a")


@pytest.mark.asyncio
async def test_call_resolve_applies_the_same_guards():
    async def explodes(url):
        raise ValueError("boom")

    plugin = FakeHoster("boom", "http://", resolve_impl=explodes)

    with pytest.raises(PluginError):
        await call_resolve(plugin, "http://x/a")


def test_the_default_timeout_is_generous_enough_for_a_wait_timer():
    # Un hoster gratuito puede hacerte esperar; el timeout es contra plugins
    # colgados, no contra plugins lentos.
    assert PLUGIN_TIMEOUT_SECONDS >= 60
