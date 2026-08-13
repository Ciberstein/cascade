"""A proxy has to cover resolution and the bytes, or it covers nothing."""

import app.plugins.ytdlp as ytdlp_mod
from app.engine.http import PROXY_ENV, outbound_client, proxy_url


def test_no_proxy_configured_means_a_direct_client(monkeypatch):
    monkeypatch.delenv(PROXY_ENV, raising=False)
    assert proxy_url() is None


def test_a_blank_value_counts_as_unset(monkeypatch):
    # Platform dashboards produce empty strings the moment someone clears a
    # field; treating "" as a proxy URL would break every download at once.
    monkeypatch.setenv(PROXY_ENV, "   ")
    assert proxy_url() is None


def test_the_proxy_is_read_per_call(monkeypatch):
    # Not captured at import: changing it has to reach the next request rather
    # than waiting for a restart.
    monkeypatch.setenv(PROXY_ENV, "http://user:pass@proxy:8080")
    assert proxy_url() == "http://user:pass@proxy:8080"
    monkeypatch.setenv(PROXY_ENV, "http://other:3128")
    assert proxy_url() == "http://other:3128"


async def test_the_client_follows_redirects_by_default(monkeypatch):
    # Almost every real download link goes through a CDN or a mirror; without
    # this an ordinary 301 lands in the queue as "error".
    monkeypatch.delenv(PROXY_ENV, raising=False)
    async with outbound_client() as client:
        assert client.follow_redirects is True


def test_cookies_are_materialised_once_and_reused(monkeypatch, tmp_path):
    monkeypatch.setattr(ytdlp_mod, "_cookie_path", None)
    monkeypatch.setenv("YTDLP_COOKIES", "# Netscape HTTP Cookie File\nfoo\tbar")

    first = ytdlp_mod._cookie_file()
    second = ytdlp_mod._cookie_file()

    # yt-dlp reads the jar on every call; rewriting it per request would be
    # disk churn for nothing.
    assert first == second
    assert "Netscape" in open(first, encoding="utf-8").read()


def test_no_cookies_configured_stays_out_of_the_way(monkeypatch):
    monkeypatch.setattr(ytdlp_mod, "_cookie_path", None)
    monkeypatch.delenv("YTDLP_COOKIES", raising=False)
    assert ytdlp_mod._cookie_file() is None
