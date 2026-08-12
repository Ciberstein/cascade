"""Merges the video and audio tracks of a quality that arrived separated.

Large sites serve high qualities as loose tracks: YouTube publishes 33 formats
and only the 360p one carries both together. Without this step, choosing a
quality would have nothing to choose above 360p.

The streams are copied without re-encoding (`-c copy`), so merging a 1 GB video
takes seconds and costs no CPU: it is only repackaged.
"""

import asyncio
import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DownloadItem, Package

logger = logging.getLogger(__name__)

#: A remux shouldn't take longer than this even for a large file. The ceiling
#: exists so a hung ffmpeg doesn't leave the item in limbo forever.
MERGE_TIMEOUT_SECONDS = 900


def part_suffix(role: str | None) -> str:
    """Filename suffix for each part while it downloads.

    Both parts live in the same folder as the result, so without distinguishing
    them they would overwrite each other.
    """
    return f".part-{role}" if role else ""


async def merge_ready_groups(db: AsyncSession) -> int:
    """Merges groups whose two parts have finished. Returns how many."""
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
            continue  # one part is still missing

        package = (
            await db.execute(select(Package).where(Package.id == video.package_id))
        ).scalar_one()

        try:
            await _merge(package.target_dir, video, audio)
        except Exception as exc:  # noqa: BLE001 - a broken group doesn't stop the others
            logger.exception("could not merge %s", video.filename)
            video.status = "error"
            video.error_message = f"could not merge the tracks: {exc}"
            await db.commit()
            continue

        # The audio part stops existing: it was a means, not a download. The
        # video item becomes the final file.
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
        # No re-encoding: repackaging takes seconds and doesn't touch the
        # quality. Re-encoding would take hours and make it worse.
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
        raise RuntimeError("ffmpeg took too long")

    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace").strip()[-300:])

    # The parts have served their purpose: keeping them would double every
    # merged video on disk.
    for path in (video_path, audio_path):
        try:
            os.remove(path)
        except OSError:
            logger.exception("no se pudo borrar la parte %s", path)
