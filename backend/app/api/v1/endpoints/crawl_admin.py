from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.crawl_job import CrawlJob
from app.models.crawl_source import CrawlSource
from app.models.user import User
from app.schemas.academic import CrawlJobOut, CrawlReindexRequest, CrawlRunRequest, CrawlSourceOut
from crawler.scheduler import crawl_scheduler

router = APIRouter(tags=["crawl-admin"])


@router.post("/crawl/run", response_model=CrawlJobOut, status_code=201)
@router.post("/crawl-admin/run", response_model=CrawlJobOut, status_code=201)
def run_crawl(
    payload: CrawlRunRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
) -> CrawlJobOut:
    return crawl_scheduler.run_crawl_job(
        db,
        current_user=current_user,
        source_slugs=payload.source_slugs,
        include_bootstrap=payload.include_bootstrap,
        include_live_sources=payload.include_live_sources,
        limit=payload.limit,
        download_only=payload.download_only,
    )


@router.post("/crawl/reindex", response_model=CrawlJobOut, status_code=201)
@router.post("/crawl-admin/reindex", response_model=CrawlJobOut, status_code=201)
def run_reindex(
    payload: CrawlReindexRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
) -> CrawlJobOut:
    return crawl_scheduler.run_reindex_job(db, current_user=current_user, source_slugs=payload.source_slugs)


@router.get("/crawl/runs/{job_id}", response_model=CrawlJobOut)
@router.get("/crawl-admin/jobs/{job_id}", response_model=CrawlJobOut)
def get_crawl_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
) -> CrawlJobOut:
    job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Crawl job not found.")
    return job


@router.get("/crawl/sources", response_model=list[CrawlSourceOut])
@router.get("/crawl-admin/sources", response_model=list[CrawlSourceOut])
def list_crawl_sources(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.ADMIN_MANAGE))],
) -> list[CrawlSourceOut]:
    crawl_scheduler.ensure_default_sources(db)
    return db.query(CrawlSource).order_by(CrawlSource.slug.asc()).all()
