"""Turns a downloaded track into what the user actually asked for.

Right now that means one thing: the soundtrack of a video, as mp3. The engine
downloads the audio track the site already publishes for its higher qualities -
a fraction of the video's size - and this converts it.

mp3 and not the native m4a or opus because of who asks for it. Someone who
wants the audio of a video wants a file that plays in a car stereo, on an old
phone, in whatever the gym uses. Those play mp3. The transcode costs seconds of
CPU on a track measured in megabytes, which is a fair price for not handing
someone a file their device refuses to open.

It runs as its own pass rather than at the end of the download for the same
reason merging does: the process can die between the last byte landing and
ffmpeg finishing, and what is pending has to be recoverable from the database
rather than from a call stack that no longer exists.
"""

import asyncio
import logging
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DownloadItem, Package

logger = logging.getLogger(__name__)

#: Audio-only transcodes are quick even for a long recording. The ceiling is
#: here so a hung ffmpeg doesn't leave the item stuck in limbo forever.
TRANSCODE_TIMEOUT_SECONDS = 600

#: Constant bitrate rather than ffmpeg's default VBR. A little larger, and it
#: plays on the old hardware that is the reason for choosing mp3 at all.
_BITRATE = "192k"


async def convert_ready_items(db: AsyncSession) -> int:
    """Transcodes the finished downloads that asked for it. Returns how many."""
    result = await db.execute(
        select(DownloadItem).where(
            DownloadItem.postprocess.is_not(None),
            DownloadItem.status == "completed",
        )
    )
    pending = result.scalars().all()

    converted = 0
    for item in pending:
        package = (
            await db.execute(select(Package).where(Package.id == item.package_id))
        ).scalar_one()

        try:
            await _to_mp3(package.target_dir, item.filename)
        except Exception as exc:  # noqa: BLE001 - one bad file doesn't stop the rest
            logger.exception("could not convert %s", item.filename)
            item.status = "error"
            item.error_message = f"could not extract the audio: {exc}"
            # Cleared either way: left set, the next tick would try again
            # forever on a file ffmpeg has already refused once.
            item.postprocess = None
            await db.commit()
            continue

        item.postprocess = None
        # The size on disk changed under it, and the row is what the progress
        # bar and the retention sweep read.
        path = os.path.join(package.target_dir, item.filename)
        if os.path.exists(path):
            item.total_size = item.downloaded_bytes = os.path.getsize(path)
        await db.commit()
        converted += 1

    return converted


async def _to_mp3(target_dir: str, filename: str) -> None:
    """Replaces the downloaded track with an mp3 of the same name.

    Written to a neighbouring file and swapped at the end, never in place:
    ffmpeg cannot read and write the same path, and a crash halfway would
    otherwise leave a truncated file that every later step treats as complete.
    """
    final_path = os.path.join(target_dir, filename)
    working_path = final_path + ".transcoding"

    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-i", final_path,
        # -vn drops anything that isn't sound: some audio tracks carry cover
        # art, and lame will not encode a picture.
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", _BITRATE,
        "-f", "mp3",
        working_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=TRANSCODE_TIMEOUT_SECONDS
        )
    except TimeoutError:
        process.kill()
        raise RuntimeError("ffmpeg took too long")

    if process.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace").strip()[-300:])

    os.replace(working_path, final_path)
