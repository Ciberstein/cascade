"""Outbound HTTP, built in one place so a proxy covers all of it.

Cascade fetches from two layers: yt-dlp resolves the real URL, and the chunk
engine pulls the bytes. A proxy applied to only one of them is worse than none
- resolution succeeds against an address the site tolerates, then the download
runs from the address it doesn't, and the failure surfaces at the byte-fetching
stage where it reads like a broken link.

The reason to want one at all: sites like YouTube judge requests by the
reputation of the address they come from. The same link that works from a home
connection answers "Sign in to confirm you're not a bot" from a cloud host, and
no amount of pretending to be a different client changes the address.
"""

import os

import httpx

#: A proxy URL, e.g. "http://user:pass@host:port". Empty means direct, which is
#: right anywhere the address isn't the problem.
PROXY_ENV = "OUTBOUND_PROXY"

#: Long enough for a slow hoster to think, short enough that a black hole is
#: reported rather than waited on forever.
_TIMEOUT_SECONDS = 30.0


def proxy_url() -> str | None:
    """The configured proxy, or None. Read per call so it can change live."""
    return os.environ.get(PROXY_ENV, "").strip() or None


def outbound_client(**kwargs) -> httpx.AsyncClient:
    """An httpx client that honours the proxy and follows redirects.

    follow_redirects is on because almost every real download link redirects to
    a CDN or a mirror; off, a perfectly ordinary 301 ends up as "error" in the
    queue.
    """
    kwargs.setdefault("timeout", _TIMEOUT_SECONDS)
    kwargs.setdefault("follow_redirects", True)
    return httpx.AsyncClient(proxy=proxy_url(), **kwargs)
