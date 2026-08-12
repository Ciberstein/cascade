"""El servidor es un lugar de paso, no un depósito.

Cascade tiene que sostener los bytes mientras descarga - de eso viven la cola,
la reanudación y los chunks en paralelo - pero no tiene por qué quedárselos
después. Este barrido borra el archivo una vez que cumplió su función y deja la
fila en el historial: lo que se va es el archivo, no el registro.

Dos reglas, por dos motivos distintos:

- Retirado hace más de `retrieval_grace_minutes`: ya está en el equipo del
  usuario. El margen no es cero a propósito - si la descarga del navegador se
  corta al 90%, borrarlo al instante lo dejaría sin nada.
- Terminado hace más de `max_retention_hours`, retirado o no: sin este tope, lo
  que nadie va a buscar se queda para siempre y el disco vuelve a crecer.
"""

import datetime as dt
import logging
import os

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DownloadItem, Package

logger = logging.getLogger(__name__)


async def sweep(db: AsyncSession, grace_minutes: int, max_retention_hours: int) -> int:
    """Borra los archivos que ya cumplieron y devuelve cuántos liberó."""
    now = dt.datetime.utcnow()
    retrieved_before = now - dt.timedelta(minutes=grace_minutes)
    finished_before = now - dt.timedelta(hours=max_retention_hours)

    result = await db.execute(
        select(DownloadItem)
        .join(Package)
        .where(
            DownloadItem.status == "completed",
            DownloadItem.file_removed_at.is_(None),
            or_(
                DownloadItem.retrieved_at < retrieved_before,
                Package.created_at < finished_before,
            ),
        )
    )
    items = result.scalars().all()
    if not items:
        return 0

    # target_dir se lee acá y no dentro del bucle sobre item.package: tocar una
    # relación no cargada dispararía una consulta perezosa por item.
    dirs = dict(
        (await db.execute(select(Package.id, Package.target_dir))).all()
    )

    freed = 0
    for item in items:
        path = os.path.join(dirs.get(item.package_id, ""), item.filename)
        try:
            os.remove(path)
            freed += 1
        except FileNotFoundError:
            pass  # ya no estaba; igual se marca para no volver a intentarlo
        except OSError:
            # Un archivo que no se puede borrar (permisos, en uso) no puede
            # frenar al resto ni al loop que llama a esto.
            logger.exception("no se pudo liberar %s", path)
            continue
        item.file_removed_at = now

    await db.commit()
    return freed
