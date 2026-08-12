"""Open directory indexes (nginx/Apache autoindex).

The simplest case of "one link contains N files", and a template for any
plugin that expands a folder.
"""

import re
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from app.plugins.base import CrawledFile, CrawlResult, DirectLink, LinkDead, UnsupportedLink

#: nginx autoindex puts the size at the end of the line, after the date.
_SIZE_AT_END_OF_LINE = re.compile(r"(\d+)\s*$")


class OpenDirectoryHoster:
    name = "open_directory"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        # Injectable so it can be tested against saved pages without a network.
        self._transport = transport

    def can_handle(self, url: str) -> bool:
        return urlparse(url).path.endswith("/")

    async def crawl(self, url: str) -> CrawlResult:
        async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
            response = await client.get(url)

        if response.status_code == 404:
            raise LinkDead(f"does not exist: {url}")
        if response.status_code >= 400:
            raise UnsupportedLink(f"status {response.status_code} at {url}")
        if "html" not in response.headers.get("Content-Type", ""):
            raise UnsupportedLink(f"{url} does not return HTML")

        files: list[CrawledFile] = []
        children: list[str] = []

        for line in response.text.splitlines():
            node = HTMLParser(line).css_first("a")
            if node is None:
                continue
            href = node.attributes.get("href")
            if not href or href.startswith("?") or href.startswith("#"):
                continue

            absolute = urljoin(url, href)
            if not absolute.startswith(url):
                continue  # "../" and any link leaving the requested tree

            if href.endswith("/"):
                children.append(absolute)
            else:
                files.append(
                    CrawledFile(
                        url=absolute,
                        filename=node.text().strip() or href,
                        size=_size_from(line),
                    )
                )

        return CrawlResult(files=files, children=children)

    async def resolve(self, url: str, format_id: str | None = None) -> DirectLink:
        # An autoindex serves the file at its own URL: nothing to sign.
        return DirectLink(url=url)


def _size_from(line: str) -> int | None:
    match = _SIZE_AT_END_OF_LINE.search(line.rstrip())
    return int(match.group(1)) if match else None


PLUGIN = OpenDirectoryHoster()
