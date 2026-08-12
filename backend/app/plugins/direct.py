"""Direct link: the pasted URL is already downloadable.

It exists as a plugin rather than a special case so the rest of the code never
has to branch between "with a plugin" and "without one".
"""

from urllib.parse import urlparse

from app.plugins.base import CrawledFile, CrawlResult, DirectLink


def filename_from_url(url: str) -> str:
    """Last segment of the URL path, falling back to "download".

    It looks at the path and not the whole URL: for "http://example.com/" the
    full URL would leave "example.com", i.e. save the file under the host name.
    And trailing slashes are stripped before splitting because, without that,
    every URL ending in "/" would fall back to "download" and two different
    folders in the same package would overwrite each other on disk.
    """
    name = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return name or "download"


class DirectHoster:
    name = "direct"

    def can_handle(self, url: str) -> bool:
        return True  # the registry asks it last, so this is the fallback

    async def crawl(self, url: str) -> CrawlResult:
        return CrawlResult(files=[CrawledFile(url=url, filename=filename_from_url(url))])

    async def resolve(self, url: str, format_id: str | None = None) -> DirectLink:
        return DirectLink(url=url)


PLUGIN = DirectHoster()
