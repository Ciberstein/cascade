import os

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user
from app.config import Settings
from app.database import get_db
from app.models import DownloadItem, Package, User
from app.schemas import CreatePackageRequest, PackageResponse

router = APIRouter(prefix="/packages", tags=["packages"])
_settings = Settings()


def _filename_from_url(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return name or "download"


@router.get("", response_model=list[PackageResponse])
async def list_packages(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Package).options(selectinload(Package.items)))
    return result.scalars().all()


@router.post("", response_model=PackageResponse, status_code=status.HTTP_201_CREATED)
async def create_package(
    payload: CreatePackageRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    package = Package(name=payload.name, status="queued", target_dir="")
    db.add(package)
    await db.flush()  # populates package.id

    package.target_dir = os.path.join(_settings.download_root, package.id)

    for url in payload.urls:
        db.add(
            DownloadItem(
                package_id=package.id,
                url=url,
                filename=_filename_from_url(url),
                status="queued",
            )
        )

    await db.commit()

    result = await db.execute(
        select(Package).options(selectinload(Package.items)).where(Package.id == package.id)
    )
    return result.scalar_one()
