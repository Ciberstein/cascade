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
    #: Token anónimo del navegador que lo creó. No hay login: este token es la
    #: identidad, y toda consulta se filtra por él.
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
    #: Qué plugin resolvió este link, para saber a cuál llamar al descargar.
    #: Nunca nulo: un enlace directo queda como "direct".
    hoster: Mapped[str] = mapped_column(String(64), default="direct")
    #: Cuándo vuelve a ser elegible. El item sigue en "queued": para la cola es
    #: trabajo pendiente que todavía no toca, no un estado distinto.
    retry_after: Mapped[dt.datetime | None] = mapped_column(default=None)
    #: Cuándo el usuario se lo bajó por primera vez. El servidor es un lugar de
    #: paso: una vez retirado, el archivo se libera.
    retrieved_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    #: Cuándo el barrido borró el archivo del disco del servidor. La fila queda
    #: en el historial; lo que se va es el archivo.
    file_removed_at: Mapped[dt.datetime | None] = mapped_column(default=None)
    #: Identificador de formato del hoster (la calidad elegida). None para lo
    #: que no es video.
    format_id: Mapped[str | None] = mapped_column(String(64), default=None)
    #: Las calidades altas vienen en pistas separadas. Las dos partes comparten
    #: este grupo y se unen cuando ambas terminan.
    merge_group: Mapped[str | None] = mapped_column(String(36), index=True, default=None)
    #: "video" o "audio" dentro del grupo. La parte de audio no se le muestra
    #: al usuario: es un medio, no una descarga que él pidió.
    merge_role: Mapped[str | None] = mapped_column(String(10), default=None)

    package: Mapped["Package"] = relationship(back_populates="items")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="item", cascade="all, delete-orphan")

    @property
    def file_removed(self) -> bool:
        """Si el archivo ya se liberó del servidor.

        Propiedad y no columna: es la misma información que file_removed_at,
        y duplicarla en la base abriría la puerta a que se contradigan.
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


class CrawlJob(Base):
    """Un pegado de links esperando a que se descubra qué hay detrás."""

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
    #: Calidades ofrecidas, serializadas. Van como JSON y no como tabla porque
    #: solo se leen enteras para pintar el selector y se descartan al promover.
    variants_json: Mapped[str | None] = mapped_column(Text, default=None)

    job: Mapped["CrawlJob"] = relationship(back_populates="results")

    @property
    def variants(self) -> list[dict]:
        """Las calidades ofrecidas, deserializadas para la respuesta."""
        import json

        return json.loads(self.variants_json) if self.variants_json else []


class User(Base):
    """Cuenta opcional. No es una puerta de entrada, es un recuperador.

    Su única función es dejar volver a obtener `owner_id` desde otro
    dispositivo. Por eso `owner_id` es único y no cambia nunca: registrarse no
    mueve un solo registro de lo ya descargado.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
