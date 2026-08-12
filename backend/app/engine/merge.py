"""Une las pistas de video y audio de una calidad que vino separada.

Los sitios grandes sirven las calidades altas en pistas sueltas: YouTube
publica 33 formatos y solo el de 360p trae las dos juntas. Sin este paso,
elegir calidad no tendría nada que elegir por encima de 360p.

Se copian los streams sin recodificar (`-c copy`), así que unir un video de
1 GB tarda segundos y no consume CPU: solo se reempaqueta.
"""

import asyncio
import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DownloadItem, Package

logger = logging.getLogger(__name__)

#: Un remux no debería tardar más que esto ni para un archivo grande. El tope
#: existe para que un ffmpeg colgado no deje el item en el limbo para siempre.
MERGE_TIMEOUT_SECONDS = 900


def part_suffix(role: str | None) -> str:
    """Sufijo del archivo de cada parte mientras se descarga.

    Las dos partes viven en la misma carpeta que el resultado, así que sin
    distinguirlas se pisarían entre sí.
    """
    return f".part-{role}" if role else ""


async def merge_ready_groups(db: AsyncSession) -> int:
    """Une los grupos cuyas dos partes ya terminaron. Devuelve cuántos unió."""
    result = await db.execute(
        select(DownloadItem).where(
            DownloadItem.merge_group.is_not(None),
            DownloadItem.merge_role == "video",
            DownloadItem.status == "completed",
        )
    )
    pending_videos = result.scalars().all()

    merged = 0
    for video in pending_videos:
        audio = (
            await db.execute(
                select(DownloadItem).where(
                    DownloadItem.merge_group == video.merge_group,
                    DownloadItem.merge_role == "audio",
                )
            )
        ).scalar_one_or_none()

        if audio is None or audio.status != "completed":
            continue  # todavía falta una parte

        package = (
            await db.execute(select(Package).where(Package.id == video.package_id))
        ).scalar_one()

        try:
            await _merge(package.target_dir, video, audio)
        except Exception as exc:  # noqa: BLE001 - un grupo roto no frena a los demás
            logger.exception("no se pudo unir %s", video.filename)
            video.status = "error"
            video.error_message = f"no se pudieron unir las pistas: {exc}"
            await db.commit()
            continue

        # La parte de audio deja de existir: era un medio, no una descarga.
        # El item de video pasa a ser el archivo final.
        video.downloaded_bytes += audio.downloaded_bytes
        video.total_size = (video.total_size or 0) + (audio.total_size or 0)
        video.merge_group = None
        video.merge_role = None
        await db.delete(audio)
        await db.commit()
        merged += 1

    return merged


async def _merge(target_dir: str, video: DownloadItem, audio: DownloadItem) -> None:
    video_path = os.path.join(target_dir, video.filename + part_suffix("video"))
    audio_path = os.path.join(target_dir, audio.filename + part_suffix("audio"))
    final_path = os.path.join(target_dir, video.filename)

    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        # Sin recodificar: reempaquetar es cuestión de segundos y no toca la
        # calidad. Recodificar tardaría horas y la empeoraría.
        "-c", "copy",
        "-map", "0:v:0", "-map", "1:a:0",
        final_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=MERGE_TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        raise RuntimeError("ffmpeg tardó demasiado")

    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace").strip()[-300:])

    # Las partes ya cumplieron: dejarlas duplicaría en disco cada video unido.
    for path in (video_path, audio_path):
        try:
            os.remove(path)
        except OSError:
            logger.exception("no se pudo borrar la parte %s", path)
