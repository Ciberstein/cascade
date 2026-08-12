import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.owner import get_owner
from app.config import Settings
from app.database import get_db
from app.models import CrawlJob, CrawlResult, DownloadItem, Package
from app.schemas import CrawlJobResponse, CreateCrawlJobRequest, PackageResponse, PromoteRequest
from app.package_dirs import target_dir_for
from app.paths import unique_name

router = APIRouter(prefix="/crawl-jobs", tags=["crawl"])
_settings = Settings()


@router.post("", response_model=CrawlJobResponse, status_code=status.HTTP_201_CREATED)
async def create_crawl_job(
    payload: CreateCrawlJobRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    job = CrawlJob(raw_input=payload.links, owner_id=owner)
    db.add(job)
    await db.commit()

    result = await db.execute(
        select(CrawlJob).options(selectinload(CrawlJob.results)).where(CrawlJob.id == job.id)
    )
    return result.scalar_one()


@router.get("", response_model=list[CrawlJobResponse])
async def list_crawl_jobs(
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    result = await db.execute(
        select(CrawlJob)
        .options(selectinload(CrawlJob.results))
        .where(CrawlJob.owner_id == owner)
        .order_by(CrawlJob.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{job_id}", response_model=CrawlJobResponse)
async def get_crawl_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    result = await db.execute(
        select(CrawlJob)
        .options(selectinload(CrawlJob.results))
        .where(CrawlJob.id == job_id, CrawlJob.owner_id == owner)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return job


@router.post("/{job_id}/promote", response_model=PackageResponse, status_code=status.HTTP_201_CREATED)
async def promote(
    job_id: str,
    payload: PromoteRequest,
    db: AsyncSession = Depends(get_db),
    owner: str = Depends(get_owner),
):
    """Turns the chosen results into a downloadable package.

    The copy is deliberate: crawl_results are a finding, download_items are
    committed work. Keeping them apart is what leaves the scheduler with its
    simple contract ("a queued item is something to download") instead of
    having to filter half-resolved rows.
    """
    owned = await db.execute(
        select(CrawlJob.id).where(CrawlJob.id == job_id, CrawlJob.owner_id == owner)
    )
    if owned.scalar_one_or_none() is None:
        # Without this, knowing someone else's job id would let you promote
        # their results into your own package.
        raise HTTPException(status_code=404, detail="Crawl job not found")

    result = await db.execute(
        select(CrawlResult).where(
            CrawlResult.crawl_job_id == job_id,
            CrawlResult.id.in_(payload.result_ids),
            # The UI already disables the checkboxes of dead links, but that
            # is presentation: without filtering here, a client can queue an
            # item whose failure is guaranteed.
            CrawlResult.status == "ok",
        )
    )
    chosen = result.scalars().all()
    if not chosen:
        raise HTTPException(status_code=404, detail="No matching crawl results")

    root = _download_root()
    package = Package(name=payload.name, status="queued", target_dir="", owner_id=owner)
    db.add(package)
    await db.flush()  # populates package.id
    package.target_dir = await target_dir_for(db, root, payload.name)

    taken: set[str] = set()
    for found in chosen:
        variant = _chosen_variant(found, payload.quality.get(found.id))
        # The extension comes from the chosen quality, not the default
        # format: a .webm with AAC audio inside cannot be written, and ffmpeg
        # only fails after both tracks have been downloaded in full.
        filename = unique_name(_with_ext(found.filename, variant), taken)

        if variant and variant.get("needs_merge"):
            # This quality comes as separate tracks: both are queued and the
            # engine merges them at the end. The audio is not shown to the user
            # - it is a means, not a download they asked for.
            group = uuid.uuid4().hex
            db.add(
                DownloadItem(
                    package_id=package.id, url=found.url, filename=filename,
                    total_size=None, hoster=found.hoster, status="queued",
                    format_id=variant["video_format"], merge_group=group, merge_role="video",
                )
            )
            db.add(
                DownloadItem(
                    package_id=package.id, url=found.url, filename=filename,
                    total_size=None, hoster=found.hoster, status="queued",
                    format_id=variant["audio_format"], merge_group=group, merge_role="audio",
                )
            )
            continue

        db.add(
            DownloadItem(
                package_id=package.id,
                url=found.url,
                # The crawler flattens the tree: "media/notes.txt" and
                # "media/sub/notes.txt" arrive here with the same name and go to
                # the same folder. Without disambiguating they would be two
                # items with one destination, and the scheduler would run them
                # together: two writers opening the same file in "r+b" and
                # seeking their own ranges. The result is one file with both
                # downloads interleaved and both items marked "completed".
                filename=filename,
                total_size=variant.get("size") if variant else found.size,
                hoster=found.hoster,
                status="queued",
                format_id=variant["video_format"] if variant else None,
            )
        )

    await db.commit()

    created = await db.execute(
        select(Package).options(selectinload(Package.items)).where(Package.id == package.id)
    )
    return created.scalar_one()



def _with_ext(filename: str, variant: dict | None) -> str:
    """Swaps the extension for the container of the chosen quality."""
    ext = (variant or {}).get("ext")
    if not ext:
        return filename
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return f"{stem}.{ext}"


def _chosen_variant(found, variant_id: str | None) -> dict | None:
    """The chosen quality, or the best available if the client didn't choose.

    Variants arrive ordered best to worst, so the first is the sensible
    default: whoever doesn't choose expects the best. An id that no longer
    exists falls back to that same default rather than failing the whole
    promotion.
    """
    variants = found.variants
    if not variants:
        return None
    if variant_id is None:
        return variants[0]
    return next((v for v in variants if v["id"] == variant_id), variants[0])


def _download_root() -> str:
    """See _target_dir_root in api/packages.py: infrastructure, not a setting."""
    return _settings.download_root
