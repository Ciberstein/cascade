"""Where a package's downloads live on disk."""

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Package
from app.paths import safe_filename, unique_name


async def target_dir_for(db: AsyncSession, root: str, name: str) -> str:
    """The package folder: `root/<sanitised name>`, never repeated.

    The user writes the name, so it goes through safe_filename before touching
    disk: without that, a package called "../.." would write outside the
    downloads folder. Phase 1 avoided this by using the generated id, which was
    safe but unreadable; sanitising gets the same guarantee with a name someone
    can actually read.

    Two packages with the same name don't share a folder - their files would
    mix, and identical names would overwrite each other.
    """
    result = await db.execute(select(Package.target_dir))
    taken = {os.path.basename(d) for d in result.scalars().all() if d}

    return os.path.join(root, unique_name(safe_filename(name, fallback="package"), taken))
