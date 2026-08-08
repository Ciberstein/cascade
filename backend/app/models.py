import datetime as dt
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
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
    #: Qué plugin resolvió este link, para saber a cuál llamar al descargar.
    #: Nunca nulo: un enlace directo queda como "direct".
    hoster: Mapped[str] = mapped_column(String(64), default="direct")
    #: Cuándo vuelve a ser elegible. El item sigue en "queued": para la cola es
    #: trabajo pendiente que todavía no toca, no un estado distinto.
    retry_after: Mapped[dt.datetime | None] = mapped_column(default=None)

    package: Mapped["Package"] = relationship(back_populates="items")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="item", cascade="all, delete-orphan")


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
    download_root: Mapped[str] = mapped_column(String(1024), default="/downloads")
    max_concurrent_downloads: Mapped[int] = mapped_column(default=3)
    chunks_per_file: Mapped[int] = mapped_column(default=4)
    max_speed_kbps: Mapped[int] = mapped_column(default=0)
    max_concurrent_crawls: Mapped[int] = mapped_column(default=5)


class CrawlJob(Base):
    """Un pegado de links esperando a que se descubra qué hay detrás."""

    __tablename__ = "crawl_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    raw_input: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    results: Mapped[list["CrawlResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class CrawlResult(Base):
    """Un archivo descubierto, todavía no encolado.

    OJO con el nombre: `app.plugins.base.CrawlResult` es otra cosa — el valor
    que devuelve un plugin (archivos + hijos a seguir). Este es la fila. Ningún
    módulo debe importar los dos; el puente entre ambos es `DiscoveredFile`.

    Qué se seleccionó no se guarda acá: vive en el cliente y viaja como lista
    de ids al confirmar. Persistirlo sería estado que mantener sincronizado
    sin que nadie lo consulte después.
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

    job: Mapped["CrawlJob"] = relationship(back_populates="results")
