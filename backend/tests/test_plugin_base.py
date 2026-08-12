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
    when = dt.datetime.utcnow() + dt.timedelta(minutes=30)
    exc = RateLimited(retry_at=when)
    assert exc.retry_at == when


def test_an_aware_retry_at_is_normalized_to_naive_utc():
    # datetime.now(UTC) es lo natural de escribir en un plugin. La columna
    # guarda UTC sin tzinfo y el scheduler compara contra utcnow(), así que sin
    # convertir acá la comparación sale corrida por el huso - y Postgres
    # directamente rechaza el valor.
    aware = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))) + dt.timedelta(minutes=30)

    exc = RateLimited(retry_at=aware)

    assert exc.retry_at.tzinfo is None
    expected = aware.astimezone(dt.timezone.utc).replace(tzinfo=None)
    assert abs((exc.retry_at - expected).total_seconds()) < 1


def test_an_absurd_wait_is_clamped_instead_of_parking_the_item_forever():
    # No hay endpoint para reencolar un item a mano, así que un bug de fecha en
    # un plugin lo dejaría detenido para siempre.
    exc = RateLimited(retry_at=dt.datetime(9999, 1, 1))

    assert exc.retry_at <= dt.datetime.utcnow() + RateLimited.MAX_WAIT


def test_a_retry_at_in_the_past_does_not_go_backwards():
    exc = RateLimited(retry_at=dt.datetime(2000, 1, 1))
    assert exc.retry_at >= dt.datetime.utcnow() - dt.timedelta(seconds=1)


def test_a_non_datetime_retry_at_is_rejected_at_the_boundary():
    # RateLimited(None) pondría retry_after=None, o sea "elegible ya", y el
    # scheduler martillaría al hoster cada 2 segundos para siempre.
    with pytest.raises(TypeError):
        RateLimited(retry_at=None)
