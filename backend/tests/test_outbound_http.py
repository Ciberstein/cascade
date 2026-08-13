"""A proxy has to cover resolution and the bytes, or it covers nothing.

The cookie jar sits next to it because both answer the same question - whether
the hoster will talk to this server at all - and both have to be changeable
while it runs.
"""

import app.plugins.ytdlp as ytdlp_mod
from app.engine.http import PROXY_ENV, outbound_client, proxy_url

JAR = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue"


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


def _forget_jar(monkeypatch):
    monkeypatch.setattr(ytdlp_mod, "_cookie_source", None)
    monkeypatch.setattr(ytdlp_mod, "_cookie_path", None)


def test_the_jar_is_written_once_and_left_alone_until_it_changes(monkeypatch):
    _forget_jar(monkeypatch)

    ytdlp_mod.set_cookies(JAR)
    first = ytdlp_mod._cookie_file()
    ytdlp_mod.set_cookies(JAR)

    # The loops push the stored jar on every tick. Rewriting it each time would
    # be disk churn for a file yt-dlp only ever reads.
    assert ytdlp_mod._cookie_file() == first
    with open(first, encoding="utf-8") as jar:
        assert "Netscape" in jar.read()


def test_a_replaced_jar_lands_without_a_restart(monkeypatch):
    _forget_jar(monkeypatch)

    ytdlp_mod.set_cookies("old jar")
    stale = ytdlp_mod._cookie_file()
    ytdlp_mod.set_cookies("new jar")

    # Cookies expire every few weeks; pasting a fresh one has to take effect on
    # the next crawl, which is the whole reason this lives in the settings row
    # rather than in the environment.
    assert ytdlp_mod._cookie_file() != stale
    with open(ytdlp_mod._cookie_file(), encoding="utf-8") as jar:
        assert jar.read().strip() == "new jar"


def test_clearing_the_jar_removes_the_file(monkeypatch):
    _forget_jar(monkeypatch)

    ytdlp_mod.set_cookies(JAR)
    ytdlp_mod.set_cookies(None)

    # A credential nobody is using any more has no business staying on disk.
    assert ytdlp_mod._cookie_file() is None


def test_whitespace_is_not_a_jar(monkeypatch):
    # Clearing the textarea leaves a newline behind; that has to read as "no
    # cookies" rather than as a jar with nothing in it, which yt-dlp would
    # accept and then send no cookies at all while claiming to be configured.
    _forget_jar(monkeypatch)
    ytdlp_mod.set_cookies("   \n  ")
    assert ytdlp_mod._cookie_file() is None
