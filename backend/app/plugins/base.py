"""The contract every hoster implements. No I/O: types and errors only."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Variant:
    """One concrete quality a video can be downloaded in.

    `video_format` and `audio_format` are the hoster's identifiers, not URLs:
    URLs expire and are requested only at download time. When `audio_format` is
    not None, that quality comes as separate tracks and they have to be merged.
    """

    id: str
    label: str
    video_format: str
    audio_format: str | None = None
    height: int | None = None
    size: int | None = None
    #: Container of the result ("mp4", "webm"). The filename has to end in this
    #: extension: a .webm with AAC audio inside cannot be written, and neither
    #: can an .mp4 with VP9.
    ext: str | None = None
    #: A step the engine runs once the bytes are down, or None for the usual
    #: case of taking the file as it arrives. "mp3" means transcode to audio.
    postprocess: str | None = None

    @property
    def needs_merge(self) -> bool:
        return self.audio_format is not None


@dataclass(frozen=True)
class CrawledFile:
    """One concrete file discovered behind a link."""

    url: str
    filename: str
    #: None when the hoster doesn't report a size until download time.
    size: int | None = None
    alive: bool = True
    #: Qualities the user can choose from. Empty for anything that isn't video:
    #: a .zip has no resolutions.
    variants: list["Variant"] = field(default_factory=list)


@dataclass(frozen=True)
class CrawlResult:
    """What sits behind a link: files, and links still to be opened."""

    files: list[CrawledFile] = field(default_factory=list)
    #: Discovered links that must themselves be crawled (folder within folder).
    children: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DirectLink:
    """A materialised downloadable URL, valid for a short while."""

    url: str
    #: Cookies, referer, or whatever that URL demands to avoid a 403.
    headers: dict[str, str] = field(default_factory=dict)


class PluginError(Exception):
    """Root of every plugin failure.

    Each call site catches this class once. If the variants below didn't share
    a root, adding a new one would mean touching every call site and, until
    then, it would escape into the loop.
    """


class LinkDead(PluginError):
    """The file no longer exists. Not retried: it isn't coming back."""


class UnsupportedLink(PluginError):
    """This plugin can't handle this URL; let the registry keep trying."""


class RateLimited(PluginError):
    """The hoster asks us to wait. Not a failure, scheduled work."""

    #: Ceiling on what a plugin may ask us to wait. An absurd value (a date bug,
    #: the year 9999) would park the item forever, and there is no endpoint to
    #: requeue it by hand.
    MAX_WAIT = dt.timedelta(hours=6)

    def __init__(self, retry_at: dt.datetime, message: str = "rate limited"):
        super().__init__(message)
        if not isinstance(retry_at, dt.datetime):
            raise TypeError(f"retry_at must be a datetime, not {type(retry_at).__name__}")

        # Normalised to naive UTC, which is what the column stores and what the
        # scheduler compares against. Without this, a plugin using
        # datetime.now(UTC) - the natural thing to write - gets compared to
        # utcnow() unconverted, and in Postgres the column won't even accept a
        # datetime carrying tzinfo.
        if retry_at.tzinfo is not None:
            retry_at = retry_at.astimezone(dt.timezone.utc).replace(tzinfo=None)

        now = dt.datetime.utcnow()
        self.retry_at = min(max(retry_at, now), now + self.MAX_WAIT)


@runtime_checkable
class Hoster(Protocol):
    """The two operations differ and happen at different moments.

    `crawl` runs when the link is added and discovers which files sit behind it.
    `resolve` runs just before downloading and returns the direct URL.

    They are separate because direct URLs expire: almost every hoster signs them
    with a single-use token or a TTL of minutes, so resolving everything at add
    time would leave a queue of 40 files with 39 expired URLs before we reach
    them.
    """

    name: str

    def can_handle(self, url: str) -> bool: ...

    async def crawl(self, url: str) -> CrawlResult: ...

    async def resolve(self, url: str, format_id: str | None = None) -> DirectLink: ...
