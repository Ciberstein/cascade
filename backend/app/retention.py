"""The server is a place to pass through, not a warehouse.

Cascade has to hold the bytes while downloading - the queue, resuming and
parallel chunks all depend on it - but it has no reason to keep them
afterwards. This sweep deletes the file once it has served its purpose and
leaves the row in the history: what goes is the file, not the record.

Two rules, for two different reasons:

- Retrieved more than `retrieval_grace_minutes` ago: it is already on the
  user's machine. The margin is deliberately not zero - if the browser's
  download breaks at 90%, deleting instantly would leave them with nothing.
- Finished more than `max_retention_hours` ago, retrieved or not: without that
  ceiling, whatever nobody comes back for stays forever and the disk grows
  again.
"""

import datetime as dt
import logging
import os

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DownloadItem, Package

logger = logging.getLogger(__name__)


async def sweep(db: AsyncSession, grace_minutes: int, max_retention_hours: int) -> int:
    """Deletes the files that have served their purpose; returns how many."""
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

    # target_dir is read here rather than inside the loop over item.package:
    # touching an unloaded relationship would fire a lazy query per item.
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
            pass  # already gone; still marked so it isn't retried forever
        except OSError:
            # A file that cannot be deleted (permissions, still in use) must
            # not stop the rest, nor the loop that calls this.
            logger.exception("could not free %s", path)
            continue
        item.file_removed_at = now

    await db.commit()
    return freed
