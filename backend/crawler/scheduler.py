from __future__ import annotations

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.academic_common import CrawlJobStatus, CrawlJobType
from app.models.crawl_job import CrawlJob
from app.models.crawl_source import CrawlSource
from app.models.user import User
from app.services.ingestion.index_service import academic_index_service
from crawler.pipelines.crawl_and_index import crawl_and_index_pipeline
from crawler.connectors.source_registry import source_registry

logger = logging.getLogger(__name__)


class CrawlScheduler:
    def ensure_default_sources(self, db: Session) -> None:
        defaults = [
            {
                "slug": "bootstrap-academic-seed",
                "name": "Bootstrap Academic Seed",
                "source_type": "bootstrap_json",
                "base_url": "data/academic_seed.json",
                "active": False,
            },
        ]
        for registry_source in source_registry.load():
            defaults.append(
                {
                    "slug": registry_source.id,
                    "name": registry_source.name,
                    "source_type": "registry_live_source",
                    "base_url": registry_source.base_url,
                    "active": registry_source.enabled,
                    "config_json": {
                        "source_id": registry_source.id,
                        "access_mode": registry_source.access_mode,
                        "crawl_strategy": registry_source.crawl_strategy,
                        "parser": registry_source.parser,
                        "expected_entities": registry_source.expected_entities,
                        "rate_limit": registry_source.rate_limit,
                    },
                    "notes": registry_source.notes,
                }
            )
        for item in defaults:
            existing = db.query(CrawlSource).filter(CrawlSource.slug == item["slug"]).first()
            if existing is None:
                db.add(CrawlSource(**item))
            else:
                existing.name = item["name"]
                existing.source_type = item["source_type"]
                existing.base_url = item["base_url"]
                existing.active = item.get("active", existing.active)
                existing.config_json = item.get("config_json", existing.config_json)
                existing.notes = item.get("notes", existing.notes)
                db.add(existing)
        db.commit()

    def run_crawl_job(
        self,
        db: Session,
        *,
        current_user: User | None,
        source_slugs: list[str] | None = None,
        include_bootstrap: bool = True,
        include_live_sources: bool = True,
        limit: int | None = None,
        download_only: bool = False,
    ) -> CrawlJob:
        self.ensure_default_sources(db)
        query = db.query(CrawlSource)
        if source_slugs:
            query = query.filter(CrawlSource.slug.in_(source_slugs))
        elif include_bootstrap:
            query = query.filter(or_(CrawlSource.active == True, CrawlSource.slug == "bootstrap-academic-seed"))
        else:
            query = query.filter(CrawlSource.active == True)
        sources = query.all()
        filtered = []
        for source in sources:
            if source.source_type == "bootstrap_json" and not include_bootstrap:
                continue
            if source.source_type == "config_live_cfp" and not include_live_sources:
                continue
            if source.source_type == "registry_live_source" and not include_live_sources:
                continue
            filtered.append(source)
        job = CrawlJob(
            job_type=CrawlJobType.CRAWL,
            status=CrawlJobStatus.PENDING,
            requested_by_user_id=current_user.id if current_user else None,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return crawl_and_index_pipeline.run(db, job, filtered, limit=limit, download_only=download_only)

    def run_reindex_job(self, db: Session, *, current_user: User | None, source_slugs: list[str] | None = None) -> CrawlJob:
        self.ensure_default_sources(db)
        job = CrawlJob(
            job_type=CrawlJobType.REINDEX,
            status=CrawlJobStatus.RUNNING,
            requested_by_user_id=current_user.id if current_user else None,
        )
        job.started_at = crawl_and_index_pipeline.utcnow()
        db.add(job)
        db.commit()
        db.refresh(job)
        try:
            stats = academic_index_service.reindex_all(db, source_slugs=source_slugs)
            job.records_indexed = sum(stats.values())
            job.job_metadata = stats
            job.status = CrawlJobStatus.SUCCEEDED
            job.finished_at = crawl_and_index_pipeline.utcnow()
            logger.info("Reindex job %s completed stats=%s", job.id, stats)
            db.add(job)
            db.commit()
            db.refresh(job)
            return job
        except Exception as exc:
            job.status = CrawlJobStatus.FAILED
            job.error_message = str(exc)
            job.finished_at = crawl_and_index_pipeline.utcnow()
            logger.exception("Reindex job %s failed", job.id)
            db.add(job)
            db.commit()
            raise


crawl_scheduler = CrawlScheduler()
