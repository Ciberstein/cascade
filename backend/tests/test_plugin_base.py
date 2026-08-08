import datetime as dt

import pytest

from app.plugins.base import (
    CrawledFile,
    CrawlResult,
    DirectLink,
    LinkDead,
    PluginError,
    RateLimited,
    UnsupportedLink,
)


def test_crawl_result_defaults_to_empty():
    result = CrawlResult()
    assert result.files == []
    assert result.children == []


def test_crawled_file_defaults_to_alive_with_unknown_size():
    f = CrawledFile(url="http://x/a.zip", filename="a.zip")
    assert f.size is None
    assert f.alive is True


def test_direct_link_defaults_to_no_extra_headers():
    assert DirectLink(url="http://x/a.zip").headers == {}


def test_every_plugin_failure_is_a_plugin_error():
    # The scheduler and the crawler each catch PluginError once. If these were
    # not a single family, every call site would need to list them all and a
    # new exception type would silently escape into the loop.
    assert issubclass(LinkDead, PluginError)
    assert issubclass(UnsupportedLink, PluginError)
    assert issubclass(RateLimited, PluginError)


def test_rate_limited_carries_when_to_retry():
    when = dt.datetime(2026, 8, 8, 15, 42, tzinfo=dt.timezone.utc)
    exc = RateLimited(retry_at=when)
    assert exc.retry_at == when
