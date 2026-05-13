from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.article_author import ArticleAuthor
from app.models.article_keyword import ArticleKeyword
from app.models.cfp_event import CFPEvent
from app.models.crawl_job import CrawlJob
from app.models.crawl_source import CrawlSource
from app.models.crawl_state import CrawlState
from app.models.raw_source_snapshot import RawSourceSnapshot
from app.models.venue import Venue
from app.models.venue_alias import VenueAlias
from app.models.venue_metric import VenueMetric
from app.models.venue_policy import VenuePolicy
from app.models.venue_subject import VenueSubject
from app.models.academic_common import CrawlJobStatus
from app.services.ingestion.dedup_service import dedup_service
from app.services.ingestion.index_service import academic_index_service
from app.services.ingestion.normalizer_service import normalizer_service
from crawler.parsers.record_parser import AcademicRecordParser
from crawler.connectors.base import SnapshotInfo
from crawler.workers.source_connector import BootstrapSeedConnector, ConfiguredCFPConnector, RegistrySourceConnector

logger = logging.getLogger(__name__)


class CrawlAndIndexPipeline:
    def __init__(self) -> None:
        self._parser = AcademicRecordParser()
        self._connectors = {
            "bootstrap_json": BootstrapSeedConnector(),
            "config_live_cfp": ConfiguredCFPConnector(),
            "registry_live_source": RegistrySourceConnector(),
        }

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def run(
        self,
        db: Session,
        job: CrawlJob,
        sources: list[CrawlSource],
        *,
        limit: int | None = None,
        download_only: bool = False,
    ) -> CrawlJob:
        job.status = CrawlJobStatus.RUNNING
        job.started_at = self.utcnow()
        db.add(job)
        db.commit()

        indexed_ids: list[tuple[str, str]] = []
        source_errors: list[dict[str, str]] = []
        try:
            for source in sources:
                state = db.query(CrawlState).filter(CrawlState.source_id == source.id).first()
                if state is None:
                    state = CrawlState(source_id=source.id)
                    db.add(state)
                    db.flush()
                connector = self._connectors.get(source.source_type)
                if source.source_type == "registry_live_source":
                    connector = RegistrySourceConnector(limit=limit, download_only=download_only)
                if connector is None:
                    state.last_error_at = self.utcnow()
                    state.error_count += 1
                    state.last_error = f"Unsupported source_type={source.source_type}"
                    source_errors.append({"source_slug": source.slug, "error": state.last_error})
                    db.add_all([source, state])
                    db.commit()
                    continue
                try:
                    if source.source_type == "registry_live_source":
                        payload = connector.fetch(source, crawl_run_id=job.id)
                    else:
                        payload = connector.fetch(source)
                    for snapshot_info in payload.get("snapshots", []) if isinstance(payload, dict) else []:
                        db.add(self._upsert_snapshot_info(db, source, snapshot_info))
                    records = self._parser.parse(source, payload)
                    logger.info("Crawl source %s yielded %d records", source.slug, len(records))
                    for record in records:
                        job.records_seen += 1
                        record_payload = record["payload"]
                        snapshot = self._upsert_snapshot(db, source, record)

                        entity_type = record["entity_type"]
                        if entity_type == "venue":
                            venue, created = self._upsert_venue(db, source, record_payload)
                            indexed_ids.append(("venue", venue.id))
                        elif entity_type == "article":
                            article, created = self._upsert_article(db, source, record_payload)
                            indexed_ids.append(("article", article.id))
                        else:
                            cfp, created = self._upsert_cfp(db, source, record_payload)
                            indexed_ids.append(("cfp", cfp.id))

                        if created:
                            job.records_created += 1
                        else:
                            job.records_updated += 1
                            job.records_deduped += 1
                        db.add(snapshot)
                    state.last_success_at = self.utcnow()
                    state.error_count = 0
                    state.last_error = None
                    state.last_seen_external_id = str(records[-1]["payload"].get("source_external_id") or records[-1]["payload"].get("title")) if records else state.last_seen_external_id
                    source.last_crawled_at = self.utcnow()
                    db.add_all([source, state])
                    if isinstance(payload, dict):
                        source_meta = {
                            "source_slug": source.slug,
                            "status": payload.get("status"),
                            "notes": payload.get("notes") or [],
                            "records_parsed": len(records),
                            "snapshots": len(payload.get("snapshots") or []),
                        }
                        metadata = job.job_metadata or {}
                        metadata.setdefault("sources", []).append(source_meta)
                        job.job_metadata = metadata
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    state = db.query(CrawlState).filter(CrawlState.source_id == source.id).first() or CrawlState(source_id=source.id)
                    state.last_error_at = self.utcnow()
                    state.error_count = (state.error_count or 0) + 1
                    state.last_error = str(exc)
                    source_errors.append({"source_slug": source.slug, "error": str(exc)})
                    logger.exception("Crawl source %s failed", source.slug)
                    db.add_all([source, state])
                    db.commit()
                    continue

            for entity_type, entity_id in indexed_ids:
                if entity_type == "venue":
                    academic_index_service.upsert_venue(db, entity_id)
                elif entity_type == "article":
                    academic_index_service.upsert_article(db, entity_id)
                else:
                    academic_index_service.upsert_cfp(db, entity_id)
                job.records_indexed += 1

            job.status = CrawlJobStatus.FAILED if source_errors else CrawlJobStatus.SUCCEEDED
            job.finished_at = self.utcnow()
            if source_errors:
                job.error_message = f"{len(source_errors)} source(s) failed during crawl"
                job.job_metadata = {"source_errors": source_errors}
            db.add(job)
            db.commit()
            db.refresh(job)
            return job
        except Exception as exc:
            job.status = CrawlJobStatus.FAILED
            job.error_message = str(exc)
            job.finished_at = self.utcnow()
            db.add(job)
            db.commit()
            raise

    def _upsert_snapshot_info(self, db: Session, source: CrawlSource, snapshot_info: SnapshotInfo) -> RawSourceSnapshot:
        external_id = snapshot_info.url
        content_hash = snapshot_info.content_hash or dedup_service.hash_value(snapshot_info.error_message or snapshot_info.url)
        snapshot = (
            db.query(RawSourceSnapshot)
            .filter(
                RawSourceSnapshot.source_id == source.id,
                RawSourceSnapshot.external_id == external_id,
                RawSourceSnapshot.content_hash == content_hash,
            )
            .first()
        )
        if snapshot is None:
            snapshot = RawSourceSnapshot(source_id=source.id, external_id=external_id, content_hash=content_hash)
        snapshot.snapshot_type = "http"
        snapshot.request_url = snapshot_info.url
        snapshot.normalized_url_hash = dedup_service.normalized_url_hash(snapshot_info.url)
        snapshot.payload_json = {
            "url": snapshot_info.url,
            "status_code": snapshot_info.status_code,
            "content_type": snapshot_info.content_type,
            "storage_path": snapshot_info.storage_path,
            "error_message": snapshot_info.error_message,
        }
        snapshot.http_status = snapshot_info.status_code
        snapshot.content_type = snapshot_info.content_type
        snapshot.content_length = snapshot_info.content_length
        snapshot.storage_path = snapshot_info.storage_path
        snapshot.error_message = snapshot_info.error_message
        snapshot.parser_version = snapshot_info.parser_version
        snapshot.crawl_run_id = snapshot_info.crawl_run_id
        snapshot.fetched_at = self.utcnow()
        return snapshot

    def _upsert_snapshot(self, db: Session, source: CrawlSource, record: dict[str, Any]) -> RawSourceSnapshot:
        record_payload = record["payload"]
        snapshot_info: SnapshotInfo | None = record.get("snapshot")
        external_id = str(record_payload.get("source_external_id") or record_payload.get("doi") or record_payload.get("url") or record_payload.get("title"))
        content_hash = snapshot_info.content_hash if snapshot_info else dedup_service.content_fingerprint(
            record_payload.get("title"),
            record_payload.get("description") or record_payload.get("abstract") or record_payload.get("scope"),
        )
        snapshot = (
            db.query(RawSourceSnapshot)
            .filter(
                RawSourceSnapshot.source_id == source.id,
                RawSourceSnapshot.external_id == external_id,
                RawSourceSnapshot.content_hash == content_hash,
            )
            .first()
        )
        if snapshot is None:
            snapshot = RawSourceSnapshot(source_id=source.id, external_id=external_id, content_hash=content_hash)
        snapshot.snapshot_type = record["entity_type"]
        snapshot.request_url = record_payload.get("source_url") or record_payload.get("url")
        snapshot.normalized_url_hash = dedup_service.normalized_url_hash(record_payload.get("source_url") or record_payload.get("url"))
        snapshot.payload_json = record_payload
        snapshot.payload_text = record_payload.get("description") or record_payload.get("abstract") or record_payload.get("scope")
        if snapshot_info:
            snapshot.http_status = snapshot_info.status_code
            snapshot.content_type = snapshot_info.content_type
            snapshot.content_length = snapshot_info.content_length
            snapshot.storage_path = snapshot_info.storage_path
            snapshot.error_message = snapshot_info.error_message
            snapshot.parser_version = snapshot_info.parser_version
            snapshot.crawl_run_id = snapshot_info.crawl_run_id
            record_payload.setdefault("fetched_at", snapshot_info.fetched_at)
            record_payload.setdefault("http_status", snapshot_info.status_code)
            record_payload.setdefault("content_hash", snapshot_info.content_hash)
            record_payload.setdefault("parser_version", snapshot_info.parser_version)
            record_payload.setdefault("crawl_run_id", snapshot_info.crawl_run_id)
            record_payload.setdefault("raw_snapshot_hash", snapshot_info.content_hash)
        snapshot.fetched_at = self.utcnow()
        return snapshot

    def _get_or_create_venue_by_key(
        self,
        db: Session,
        venue_title: str | None,
        publisher: str | None,
        *,
        issn: str | None = None,
        eissn: str | None = None,
    ) -> Venue | None:
        if issn:
            venue = db.query(Venue).filter((Venue.issn_print == issn) | (Venue.issn_electronic == issn)).first()
            if venue:
                return venue
        if eissn:
            venue = db.query(Venue).filter((Venue.issn_print == eissn) | (Venue.issn_electronic == eissn)).first()
            if venue:
                return venue
        if not venue_title:
            return None
        canonical_title = normalizer_service.normalize_text(venue_title)
        normalized_publisher = normalizer_service.normalize_text(publisher)
        query = db.query(Venue).filter(Venue.canonical_title == canonical_title)
        if normalized_publisher:
            publisher_match = query.filter(Venue.publisher == normalized_publisher).first()
            if publisher_match is not None:
                return publisher_match
        return query.first()

    def _upsert_venue(self, db: Session, source: CrawlSource, raw: dict[str, Any]) -> tuple[Venue, bool]:
        normalized = normalizer_service.normalize_venue(raw)
        business_key = dedup_service.business_key_for_venue(
            normalized["canonical_title"],
            normalized.get("publisher"),
            normalized.get("issn_print") or normalized.get("issn_electronic"),
        )
        fingerprint = dedup_service.find_existing(
            db,
            entity_type="venue",
            source_name=source.slug,
            raw_identifier=normalized["canonical_title"],
            normalized_url_hash=dedup_service.normalized_url_hash(normalized.get("homepage_url")),
            business_key=business_key,
            content_fingerprint=dedup_service.content_fingerprint(normalized["title"], normalized.get("aims_scope")),
        )
        created = False
        venue = db.query(Venue).filter(Venue.id == fingerprint.entity_id).first() if fingerprint else None
        if venue is None:
            venue = self._get_or_create_venue_by_key(
                db,
                normalized["canonical_title"],
                normalized.get("publisher"),
                issn=normalized.get("issn_print"),
                eissn=normalized.get("issn_electronic"),
            )
        if venue is None:
            venue = Venue(**{key: value for key, value in normalized.items() if key not in {"subjects", "aliases", "policy", "metric"}})
            db.add(venue)
            db.flush()
            created = True
        else:
            for key, value in normalized.items():
                if key in {"subjects", "aliases", "policy", "metric"}:
                    continue
                if value not in (None, "", []):
                    setattr(venue, key, value)
            db.add(venue)
            db.flush()

        existing_subjects = {subject.label.lower(): subject for subject in venue.subjects}
        for label in normalized["subjects"]:
            if label.lower() not in existing_subjects:
                db.add(VenueSubject(venue_id=venue.id, label=label, source=source.slug, scheme="keyword"))

        alias_keys = {alias.alias_normalized for alias in venue.aliases}
        for alias in normalized["aliases"]:
            normalized_alias = normalizer_service.normalize_text(alias).lower()
            if normalized_alias not in alias_keys:
                db.add(VenueAlias(venue_id=venue.id, alias=alias, alias_normalized=normalized_alias))

        metric_payload = normalized["metric"]
        if any(value is not None for value in metric_payload.values()):
            metric = (
                db.query(VenueMetric)
                .filter(VenueMetric.venue_id == venue.id, VenueMetric.metric_name.is_(None), VenueMetric.source_id.is_(None))
                .order_by(VenueMetric.metric_year.desc().nullslast())
                .first()
            )
            if metric is None:
                metric = VenueMetric(venue_id=venue.id, **metric_payload)
            else:
                for key, value in metric_payload.items():
                    setattr(metric, key, value)
            db.add(metric)

        for metric_raw in raw.get("metrics") or []:
            metric_name = metric_raw.get("metric_name")
            if not metric_name:
                continue
            metric = (
                db.query(VenueMetric)
                .filter(
                    VenueMetric.venue_id == venue.id,
                    VenueMetric.source_id == source.slug,
                    VenueMetric.metric_name == metric_name,
                    VenueMetric.metric_year == metric_raw.get("metric_year", normalized["metric"].get("metric_year")),
                )
                .first()
            )
            if metric is None:
                metric = VenueMetric(venue_id=venue.id, source_id=source.slug, metric_name=metric_name)
            metric.metric_year = metric_raw.get("metric_year", normalized["metric"].get("metric_year"))
            metric.metric_value = metric_raw.get("metric_value")
            metric.metric_text = metric_raw.get("metric_text")
            if metric_name.lower() == "sjr quartile":
                metric.sjr_quartile = metric_raw.get("metric_text")
            if metric_name.lower() == "h_index" and metric_raw.get("metric_value") is not None:
                metric.h_index = int(metric_raw["metric_value"])
            db.add(metric)

        policy_payload = normalized["policy"]
        if any(value is not None and value != "" for value in policy_payload.values()):
            policy = db.query(VenuePolicy).filter(VenuePolicy.venue_id == venue.id).first()
            if policy is None:
                policy = VenuePolicy(venue_id=venue.id, **policy_payload)
            else:
                for key, value in policy_payload.items():
                    setattr(policy, key, value)
            db.add(policy)

        dedup_service.upsert_fingerprint(
            db,
            entity_type="venue",
            entity_id=venue.id,
            source_name=source.slug,
            raw_identifier=normalized["canonical_title"],
            normalized_url_hash=dedup_service.normalized_url_hash(normalized.get("homepage_url")),
            business_key=business_key,
            content_fingerprint=dedup_service.content_fingerprint(normalized["title"], normalized.get("aims_scope")),
        )
        db.flush()
        return venue, created

    def _upsert_article(self, db: Session, source: CrawlSource, raw: dict[str, Any]) -> tuple[Article, bool]:
        normalized = normalizer_service.normalize_article(raw)
        venue = self._get_or_create_venue_by_key(db, raw.get("venue_title") or raw.get("venue_key"), normalized.get("publisher"))
        business_key = dedup_service.business_key_for_article(
            normalized["title"],
            venue.title if venue else raw.get("venue_title"),
            normalized.get("publication_year"),
            normalized.get("doi"),
        )
        fingerprint = dedup_service.find_existing(
            db,
            entity_type="article",
            source_name=source.slug,
            raw_identifier=normalized.get("source_external_id"),
            normalized_url_hash=dedup_service.normalized_url_hash(normalized.get("url")),
            business_key=business_key,
            content_fingerprint=dedup_service.content_fingerprint(normalized["title"], normalized.get("abstract")),
        )
        created = False
        article = db.query(Article).filter(Article.id == fingerprint.entity_id).first() if fingerprint else None
        if article is None:
            article = Article(venue_id=venue.id if venue else None, **{key: value for key, value in normalized.items() if key not in {"keywords", "authors"}})
            db.add(article)
            db.flush()
            created = True
        else:
            article.venue_id = venue.id if venue else article.venue_id
            for key, value in normalized.items():
                if key in {"keywords", "authors"}:
                    continue
                setattr(article, key, value)
            db.add(article)
            db.flush()

        db.query(ArticleKeyword).filter(ArticleKeyword.article_id == article.id).delete()
        for keyword in normalized["keywords"]:
            db.add(ArticleKeyword(article_id=article.id, keyword=keyword, normalized_keyword=keyword.lower()))

        db.query(ArticleAuthor).filter(ArticleAuthor.article_id == article.id).delete()
        for order, author in enumerate(normalized["authors"], start=1):
            if isinstance(author, dict):
                db.add(
                    ArticleAuthor(
                        article_id=article.id,
                        full_name=author.get("full_name") or author.get("name") or "Unknown",
                        affiliation=author.get("affiliation"),
                        orcid=author.get("orcid"),
                        author_order=order,
                    )
                )
            else:
                db.add(ArticleAuthor(article_id=article.id, full_name=str(author), author_order=order))

        dedup_service.upsert_fingerprint(
            db,
            entity_type="article",
            entity_id=article.id,
            source_name=source.slug,
            raw_identifier=normalized.get("source_external_id"),
            normalized_url_hash=dedup_service.normalized_url_hash(normalized.get("url")),
            business_key=business_key,
            content_fingerprint=dedup_service.content_fingerprint(normalized["title"], normalized.get("abstract")),
        )
        db.flush()
        return article, created

    def _upsert_cfp(self, db: Session, source: CrawlSource, raw: dict[str, Any]) -> tuple[CFPEvent, bool]:
        normalized = normalizer_service.normalize_cfp(raw)
        venue = self._get_or_create_venue_by_key(db, raw.get("venue_title") or raw.get("publisher"), normalized.get("publisher"))
        business_key = dedup_service.business_key_for_cfp(
            normalized["title"],
            venue.title if venue else raw.get("venue_title") or raw.get("publisher"),
            normalized["full_paper_deadline"].isoformat() if normalized.get("full_paper_deadline") else None,
        )
        fingerprint = dedup_service.find_existing(
            db,
            entity_type="cfp",
            source_name=source.slug,
            raw_identifier=normalized.get("source_url") or normalized["title"],
            normalized_url_hash=dedup_service.normalized_url_hash(normalized.get("source_url")),
            business_key=business_key,
            content_fingerprint=dedup_service.content_fingerprint(normalized["title"], normalized.get("description")),
        )
        created = False
        cfp = db.query(CFPEvent).filter(CFPEvent.id == fingerprint.entity_id).first() if fingerprint else None
        if cfp is None:
            cfp = CFPEvent(venue_id=venue.id if venue else None, **normalized)
            db.add(cfp)
            db.flush()
            created = True
        else:
            cfp.venue_id = venue.id if venue else cfp.venue_id
            for key, value in normalized.items():
                setattr(cfp, key, value)
            db.add(cfp)
            db.flush()

        dedup_service.upsert_fingerprint(
            db,
            entity_type="cfp",
            entity_id=cfp.id,
            source_name=source.slug,
            raw_identifier=normalized.get("source_url") or normalized["title"],
            normalized_url_hash=dedup_service.normalized_url_hash(normalized.get("source_url")),
            business_key=business_key,
            content_fingerprint=dedup_service.content_fingerprint(normalized["title"], normalized.get("description")),
        )
        db.flush()
        return cfp, created


crawl_and_index_pipeline = CrawlAndIndexPipeline()
