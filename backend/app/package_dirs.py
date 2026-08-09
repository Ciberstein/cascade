"""Dónde vive en disco lo que baja un paquete."""

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Package
from app.paths import safe_filename, unique_name


async def target_dir_for(db: AsyncSession, root: str, name: str) -> str:
    """Carpeta del paquete: `root/<nombre saneado>`, sin repetir.

    El nombre lo escribe el usuario, así que pasa por safe_filename antes de
    tocar el disco: sin eso, un paquete llamado "../.." escribiría fuera de la
    carpeta de descargas. Fase 1 evitaba esto usando el id generado, que era
    seguro pero ilegible; sanear permite lo mismo con un nombre que se entienda.

    Dos paquetes con el mismo nombre no comparten carpeta - se mezclarían sus
    archivos y, con nombres iguales, se pisarían.
    """
    result = await db.execute(select(Package.target_dir))
    taken = {os.path.basename(d) for d in result.scalars().all() if d}

    return os.path.join(root, unique_name(safe_filename(name, fallback="paquete"), taken))
