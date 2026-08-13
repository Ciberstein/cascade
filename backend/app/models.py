import datetime as dt
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    #: Anonymous token of the browser that created it. There is no login:
    #: this token is the identity, and every query filters by it.
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    target_dir: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)

    items: Mapped[list["DownloadItem"]] = relationship(back_populates="package", cascade="all, delete-orphan")


class DownloadItem(Base):
    __tablename__ = "download_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    package_id: Mapped[str] = mapped_column(ForeignKey("packages.id"))
    url: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(1024))
    total_size: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    downloaded_bytes: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    retries: Mapped[int] = mapped_column(default=0)
    #: Which plugin resolved this link, so we know which one to call when
    #: downloading. Never null: a plain link is recorded as "direct".
    hoster: Mapped[str] = mapped_column(String(64), default="direct")
    #: When it becomes eligible again. The item stays "queued": to the queue
    #: it is pending work whose turn hasn't come, not a separate state.
    retry_after: Mapped[dt.datetime | None] = mapped_column(default=None)
    #: When the user first fetched it. The server is a place to pass through:
    #: once retrieved, the file is freed.
    retrieved_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    #: When the sweep deleted the file from the server's disk. The row stays
    #: in the history; what goes is the file.
    file_removed_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    #: The hoster's format identifier (the chosen quality). None for anything
    #: that isn't video.
    format_id: Mapped[str | None] = mapped_column(String(64), default=None)
    #: High qualities arrive as separate tracks. Both parts share this group
    #: and are merged once they have both finished.
    merge_group: Mapped[str | None] = mapped_column(String(36), index=True, default=None)
    #: "video" or "audio" within the group. The audio part is not shown to the
    #: user: it is a means, not a download they asked for.
    merge_role: Mapped[str | None] = mapped_column(String(10), default=None)
    #: A step still owed once the bytes are down ("mp3"), or None. A column and
    #: not a flag in memory: the process can die between the last byte landing
    #: and ffmpeg finishing, and the work still owed has to survive that.
    postprocess: Mapped[str | None] = mapped_column(String(16), default=None)

    package: Mapped["Package"] = relationship(back_populates="items")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="item", cascade="all, delete-orphan")

    @property
    def retrieved(self) -> bool:
        """Whether the user has already taken it. The browser uses this to
        avoid firing it again on every poll."""
        return self.retrieved_at is not None

    @property
    def file_removed(self) -> bool:
        """Whether the file has already been freed from the server.

        A property and not a column: it is the same information as
        file_removed_at, and duplicating it in the database would open the door
        to the two contradicting each other.
        """
        return self.file_removed_at is not None


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    download_item_id: Mapped[str] = mapped_column(ForeignKey("download_items.id"))
    range_start: Mapped[int] = mapped_column()
    range_end: Mapped[int] = mapped_column()
    downloaded_bytes: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    item: Mapped["DownloadItem"] = relationship(back_populates="chunks")


class GlobalSettings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    max_concurrent_downloads: Mapped[int] = mapped_column(default=3)
    chunks_per_file: Mapped[int] = mapped_column(default=4)
    max_speed_kbps: Mapped[int] = mapped_column(default=0)
    max_concurrent_crawls: Mapped[int] = mapped_column(default=5)
    #: Netscape cookie jar handed to the hoster plugins.
    #:
    #: Here rather than in the environment because these expire every few weeks
    #: and replacing one must not need a redeploy. Never returned by the API -
    #: see SettingsResponse.
    hoster_cookies: Mapped[str | None] = mapped_column(Text, default=None)

    @property
    def has_cookies(self) -> bool:
        """What the API is allowed to say about the jar: that there is one.

        A property and not a column for the same reason as DownloadItem's: it
        is derived, and storing it separately would let the two disagree.
        """
        return bool(self.hoster_cookies)


class CrawlJob(Base):
    """A paste of links waiting for what is behind them to be discovered."""

    __tablename__ = "crawl_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    raw_input: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    results: Mapped[list["CrawlResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class CrawlResult(Base):
    """A discovered file, not queued yet.

    Careful with the name: `app.plugins.base.CrawlResult` is a different thing -
    the value a plugin returns (files + children to follow). This one is the
    row. No module should import both; the bridge between them is
    `DiscoveredFile`.

    What was selected is not stored here: it lives in the client and travels as
    a list of ids on confirmation. Persisting it would be state to keep in sync
    that nobody reads afterwards.
    """

    __tablename__ = "crawl_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    crawl_job_id: Mapped[str] = mapped_column(ForeignKey("crawl_jobs.id"))
    url: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(1024))
    size: Mapped[int | None] = mapped_column(default=None)
    hoster: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    #: The offered qualities, serialised. JSON rather than a table because they
    #: are only read whole to paint the picker, and discarded on promotion.
    variants_json: Mapped[str | None] = mapped_column(Text, default=None)

    job: Mapped["CrawlJob"] = relationship(back_populates="results")

    @property
    def variants(self) -> list[dict]:
        """The offered qualities, deserialised for the response."""
        import json

        return json.loads(self.variants_json) if self.variants_json else []


class User(Base):
    """Optional account. Not a front door, a way to recover.

    Its only job is to let `owner_id` be obtained again from another device.
    That is why `owner_id` is unique and never changes: registering does not
    move a single row of what has already been downloaded.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
