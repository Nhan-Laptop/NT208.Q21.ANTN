from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.article import Article
from app.models.cfp_event import CFPEvent
from app.models.entity_fingerprint import EntityFingerprint
from app.models.venue import Venue
from app.models.venue_metric import VenueMetric
from app.services.embeddings.specter2_service import specter2_service

logger = logging.getLogger(__name__)

try:
    import chromadb
except ImportError:  # pragma: no cover - optional dependency guard
    chromadb = None  # type: ignore[assignment]


class AcademicIndexService:
    COLLECTIONS = {
        "venue_profiles": "venue_profiles",
        "cfp_notices": "cfp_notices",
        "article_exemplars": "article_exemplars",
    }

    def __init__(self) -> None:
        self._client = None

    def _db_path(self) -> Path:
        backend_root = Path(__file__).resolve().parents[3]
        return (backend_root / settings.chroma_db_path).resolve()

    def _get_client(self):
        if chromadb is None:
            raise RuntimeError("chromadb is not installed.")
        if self._client is None:
            path = self._db_path()
            path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(path))
        return self._client

    def ensure_collections(self) -> None:
        client = self._get_client()
        for name in self.COLLECTIONS.values():
            client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    def collection_counts(self) -> dict[str, int]:
        try:
            self.ensure_collections()
        except Exception as exc:
            logger.warning("Chroma collection bootstrap unavailable: %s", exc)
            return {name: 0 for name in self.COLLECTIONS.values()}
        counts: dict[str, int] = {}
        for name in self.COLLECTIONS.values():
            try:
                counts[name] = int(self._collection(name).count())
            except Exception as exc:
                logger.warning("Failed counting Chroma collection %s: %s", name, exc)
                counts[name] = 0
        return counts

    def status(self) -> dict[str, Any]:
        available = chromadb is not None
        try:
            self.ensure_collections()
        except Exception as exc:
            logger.warning("Chroma status check unavailable: %s", exc)
            available = False
        counts = self.collection_counts() if available else {name: 0 for name in self.COLLECTIONS.values()}
        return {
            "available": available,
            "counts": counts,
            "embedding": specter2_service.status(),
            "path": str(self._db_path()),
        }

    def _collection(self, name: str):
        self.ensure_collections()
        return self._get_client().get_collection(name)

    def _reset_collection(self, name: str) -> None:
        client = self._get_client()
        try:
            client.delete_collection(name)
        except Exception as exc:
            logger.warning("Failed deleting Chroma collection %s before reset: %s", name, exc)
        client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    def _reset_collections_for_current_embedding(self) -> None:
        current_model = specter2_service.embedding_model_name
        for collection_name in self.COLLECTIONS.values():
            collection = self._collection(collection_name)
            if collection.count() == 0:
                continue
            rows = collection.get(include=["metadatas"])
            metadata_models = {
                metadata.get("embedding_model")
                for metadata in rows.get("metadatas", [])
                if isinstance(metadata, dict) and metadata.get("embedding_model")
            }
            if metadata_models != {current_model}:
                logger.warning(
                    "Resetting Chroma collection %s because indexed embedding models %s do not match %s",
                    collection_name,
                    sorted(metadata_models),
                    current_model,
                )
                self._reset_collection(collection_name)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, list):
                clean[key] = ", ".join(str(item) for item in value if item is not None)
            elif isinstance(value, (str, bool, int, float)):
                clean[key] = value
            else:
                clean[key] = str(value)
        return clean

    @staticmethod
    def _quartile(metric: VenueMetric | None) -> tuple[str | None, str | None]:
        if metric is None:
            return None, None
        return metric.sjr_quartile, metric.jcr_quartile

    def _latest_metric(self, venue: Venue) -> VenueMetric | None:
        ordered = sorted(venue.metrics, key=lambda metric: (metric.metric_year or 0, metric.updated_at), reverse=True)
        return ordered[0] if ordered else None

    def build_venue_document(self, venue: Venue) -> tuple[str, dict[str, Any]]:
        metric = self._latest_metric(venue)
        subject_labels = [subject.label for subject in venue.subjects]
        policy_notes = " ".join(policy.notes or "" for policy in venue.policies if policy.notes)
        source_ids = sorted({metric.source_id for metric in venue.metrics if metric.source_id})
        metric_names = sorted({metric.metric_name for metric in venue.metrics if metric.metric_name})
        document = " ".join(
            part
            for part in [
                f"Journal: {venue.title}" if venue.venue_type.value == "journal" else f"Venue: {venue.title}",
                f"ISSN: {venue.issn_print}" if venue.issn_print else "",
                f"eISSN: {venue.issn_electronic}" if venue.issn_electronic else "",
                f"Publisher: {venue.publisher}" if venue.publisher else "",
                venue.aims_scope or "",
                "Subjects: " + ", ".join(subject_labels) if subject_labels else "",
                "Metrics: " + ", ".join(metric_names) if metric_names else "",
                "Source: " + ", ".join(source_ids) if source_ids else "",
                policy_notes,
            ]
            if part
        )
        sjr_quartile, jcr_quartile = self._quartile(metric)
        metadata = self._clean_metadata(
            {
                "entity_type": "venue",
                "venue_id": venue.id,
                "venue_type": venue.venue_type.value,
                "title": venue.title,
                "publisher": venue.publisher,
                "homepage_url": venue.homepage_url,
                "subject_labels": subject_labels,
                "source_ids": source_ids,
                "source_names": source_ids,
                "issn": venue.issn_print,
                "eissn": venue.issn_electronic,
                "metric_names": metric_names,
                "provenance_hash": "|".join(source_ids + metric_names) or venue.id,
                "sjr_quartile": sjr_quartile,
                "jcr_quartile": jcr_quartile,
                "citescore": metric.citescore if metric else None,
                "impact_factor": metric.impact_factor if metric else None,
                "h_index": metric.h_index if metric else None,
                "is_open_access": venue.is_open_access,
                "is_hybrid": venue.is_hybrid,
                "avg_review_weeks": venue.avg_review_weeks if venue.avg_review_weeks is not None else metric.avg_review_weeks if metric else None,
                "acceptance_rate": venue.acceptance_rate if venue.acceptance_rate is not None else metric.acceptance_rate if metric else None,
                "indexed_scopus": venue.indexed_scopus,
                "indexed_wos": venue.indexed_wos,
                "country": venue.country,
                "active": venue.active,
                "apc_usd": next((policy.apc_usd for policy in venue.policies if policy.apc_usd is not None), venue.apc_usd_max),
                "embedding_model": specter2_service.embedding_model_name,
                "last_indexed_at": self._timestamp(),
            }
        )
        return document, metadata

    def build_cfp_document(self, cfp: CFPEvent) -> tuple[str, dict[str, Any]]:
        venue = cfp.venue
        metric = self._latest_metric(venue) if venue else None
        sjr_quartile, jcr_quartile = self._quartile(metric)
        document = " ".join(
            part
            for part in [
                f"Call for papers: {cfp.title}",
                cfp.description or "",
                "Topics: " + ", ".join(cfp.topic_tags or []) if cfp.topic_tags else "",
                f"Venue: {venue.title}" if venue else "",
                f"Deadline: {cfp.full_paper_deadline.isoformat()}" if cfp.full_paper_deadline else "",
                f"Source: {cfp.source_name or ''} {cfp.source_url or ''}".strip(),
            ]
            if part
        )
        metadata = self._clean_metadata(
            {
                "entity_type": "cfp",
                "cfp_event_id": cfp.id,
                "venue_id": cfp.venue_id,
                "venue_title": venue.title if venue else None,
                "venue_type": venue.venue_type.value if venue else None,
                "title": cfp.title,
                "topic_tags": cfp.topic_tags or [],
                "source_ids": [cfp.source_name] if cfp.source_name else [],
                "source_names": [cfp.source_name] if cfp.source_name else [],
                "provenance_hash": cfp.source_url or cfp.id,
                "sjr_quartile": sjr_quartile,
                "jcr_quartile": jcr_quartile,
                "citescore": metric.citescore if metric else None,
                "impact_factor": metric.impact_factor if metric else None,
                "h_index": metric.h_index if metric else None,
                "status": cfp.status,
                "abstract_deadline": cfp.abstract_deadline.isoformat() if cfp.abstract_deadline else None,
                "full_paper_deadline": cfp.full_paper_deadline.isoformat() if cfp.full_paper_deadline else None,
                "mode": cfp.mode,
                "freshness_score": self._cfp_freshness(cfp),
                "publisher": cfp.publisher or (venue.publisher if venue else None),
                "source_url": cfp.source_url,
                "indexed_scopus": cfp.indexed_scopus or bool(venue and venue.indexed_scopus),
                "indexed_wos": cfp.indexed_wos or bool(venue and venue.indexed_wos),
                "is_open_access": venue.is_open_access if venue else None,
                "avg_review_weeks": venue.avg_review_weeks if venue and venue.avg_review_weeks is not None else metric.avg_review_weeks if metric else None,
                "acceptance_rate": venue.acceptance_rate if venue and venue.acceptance_rate is not None else metric.acceptance_rate if metric else None,
                "apc_usd": next((policy.apc_usd for policy in venue.policies if policy.apc_usd is not None), venue.apc_usd_max) if venue else None,
                "embedding_model": specter2_service.embedding_model_name,
                "last_indexed_at": self._timestamp(),
            }
        )
        return document, metadata

    def build_article_document(self, article: Article) -> tuple[str, dict[str, Any]]:
        keywords = [keyword.keyword for keyword in article.keywords]
        venue = article.venue
        subjects = [subject.label for subject in venue.subjects] if venue else []
        metric = self._latest_metric(venue) if venue else None
        sjr_quartile, jcr_quartile = self._quartile(metric)
        document = " ".join(
            part
            for part in [
                article.title,
                article.abstract or "",
                "Keywords: " + ", ".join(keywords) if keywords else "",
                f"Venue: {venue.title}" if venue else "",
            ]
            if part
        )
        metadata = self._clean_metadata(
            {
                "entity_type": "article",
                "article_id": article.id,
                "venue_id": article.venue_id,
                "venue_title": venue.title if venue else None,
                "venue_homepage_url": venue.homepage_url if venue else None,
                "title": article.title,
                "doi": article.doi,
                "url": article.url,
                "publication_year": article.publication_year,
                "venue_type": venue.venue_type.value if venue else None,
                "publisher": article.publisher or (venue.publisher if venue else None),
                "subject_labels": subjects,
                "sjr_quartile": sjr_quartile,
                "jcr_quartile": jcr_quartile,
                "citescore": metric.citescore if metric else None,
                "impact_factor": metric.impact_factor if metric else None,
                "h_index": metric.h_index if metric else None,
                "indexed_scopus": article.indexed_scopus or bool(venue and venue.indexed_scopus),
                "indexed_wos": article.indexed_wos or bool(venue and venue.indexed_wos),
                "is_open_access": venue.is_open_access if venue else None,
                "avg_review_weeks": venue.avg_review_weeks if venue and venue.avg_review_weeks is not None else metric.avg_review_weeks if metric else None,
                "acceptance_rate": venue.acceptance_rate if venue and venue.acceptance_rate is not None else metric.acceptance_rate if metric else None,
                "apc_usd": next((policy.apc_usd for policy in venue.policies if policy.apc_usd is not None), venue.apc_usd_max) if venue else None,
                "is_retracted": article.is_retracted,
                "embedding_model": specter2_service.embedding_model_name,
                "last_indexed_at": self._timestamp(),
            }
        )
        return document, metadata

    def _cfp_freshness(self, cfp: CFPEvent) -> float:
        deadline = cfp.full_paper_deadline or cfp.abstract_deadline
        if deadline is None:
            return 0.3
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        delta_days = (deadline - datetime.now(timezone.utc)).days
        if delta_days < 0:
            return 0.0
        if delta_days < 30:
            return 1.0
        if delta_days < 120:
            return 0.8
        return 0.6

    def _upsert(self, collection_name: str, *, record_id: str, document: str, metadata: dict[str, Any]) -> None:
        collection = self._collection(collection_name)
        embedding = specter2_service.embed_text(document)
        collection.upsert(ids=[record_id], documents=[document], metadatas=[metadata], embeddings=[embedding])

    def _prune_stale(self, collection_name: str, valid_ids: set[str]) -> None:
        collection = self._collection(collection_name)
        try:
            existing = collection.get(include=[])
        except Exception as exc:
            logger.warning("Skipping stale Chroma prune for %s: %s", collection_name, exc)
            return
        stale_ids = [identifier for identifier in existing.get("ids", []) if identifier not in valid_ids]
        if stale_ids:
            collection.delete(ids=stale_ids)

    def upsert_venue(self, db: Session, venue_id: str) -> None:
        venue = (
            db.query(Venue)
            .options(selectinload(Venue.subjects), selectinload(Venue.metrics), selectinload(Venue.policies))
            .filter(Venue.id == venue_id)
            .first()
        )
        if venue is None:
            return
        document, metadata = self.build_venue_document(venue)
        self._upsert(self.COLLECTIONS["venue_profiles"], record_id=f"venue:{venue.id}", document=document, metadata=metadata)

    def upsert_cfp(self, db: Session, cfp_id: str) -> None:
        cfp = (
            db.query(CFPEvent)
            .options(
                selectinload(CFPEvent.venue).selectinload(Venue.metrics),
                selectinload(CFPEvent.venue).selectinload(Venue.policies),
            )
            .filter(CFPEvent.id == cfp_id)
            .first()
        )
        if cfp is None:
            return
        document, metadata = self.build_cfp_document(cfp)
        self._upsert(self.COLLECTIONS["cfp_notices"], record_id=f"cfp:{cfp.id}", document=document, metadata=metadata)

    def upsert_article(self, db: Session, article_id: str) -> None:
        article = (
            db.query(Article)
            .options(
                selectinload(Article.keywords),
                selectinload(Article.venue).selectinload(Venue.subjects),
                selectinload(Article.venue).selectinload(Venue.metrics),
                selectinload(Article.venue).selectinload(Venue.policies),
            )
            .filter(Article.id == article_id)
            .first()
        )
        if article is None:
            return
        document, metadata = self.build_article_document(article)
        self._upsert(self.COLLECTIONS["article_exemplars"], record_id=f"article:{article.id}", document=document, metadata=metadata)

    def reindex_all(self, db: Session, source_slugs: list[str] | None = None) -> dict[str, int]:
        self.ensure_collections()
        if source_slugs is None:
            self._reset_collections_for_current_embedding()
        valid_ids = {
            "venue_profiles": set(),
            "cfp_notices": set(),
            "article_exemplars": set(),
        }
        source_filter: dict[str, set[str]] | None = None
        if source_slugs:
            source_filter = {
                "venue": {row.entity_id for row in db.query(EntityFingerprint).filter(EntityFingerprint.entity_type == "venue", EntityFingerprint.source_name.in_(source_slugs)).all()},
                "article": {row.entity_id for row in db.query(EntityFingerprint).filter(EntityFingerprint.entity_type == "article", EntityFingerprint.source_name.in_(source_slugs)).all()},
                "cfp": {row.entity_id for row in db.query(EntityFingerprint).filter(EntityFingerprint.entity_type == "cfp", EntityFingerprint.source_name.in_(source_slugs)).all()},
            }
        venue_count = 0
        venue_query = db.query(Venue)
        if source_filter is not None:
            venue_query = venue_query.filter(Venue.id.in_(source_filter["venue"] or {"__none__"}))
        for venue in venue_query.all():
            self.upsert_venue(db, venue.id)
            venue_count += 1
            valid_ids["venue_profiles"].add(f"venue:{venue.id}")
        cfp_count = 0
        cfp_query = db.query(CFPEvent)
        if source_filter is not None:
            cfp_query = cfp_query.filter(CFPEvent.id.in_(source_filter["cfp"] or {"__none__"}))
        for cfp in cfp_query.all():
            self.upsert_cfp(db, cfp.id)
            cfp_count += 1
            valid_ids["cfp_notices"].add(f"cfp:{cfp.id}")
        article_count = 0
        article_query = db.query(Article)
        if source_filter is not None:
            article_query = article_query.filter(Article.id.in_(source_filter["article"] or {"__none__"}))
        for article in article_query.all():
            self.upsert_article(db, article.id)
            article_count += 1
            valid_ids["article_exemplars"].add(f"article:{article.id}")
        if source_slugs is None:
            for collection_name, ids in valid_ids.items():
                self._prune_stale(collection_name, ids)
        return {"venues": venue_count, "cfps": cfp_count, "articles": article_count}

    def query_all(self, query_text: str, top_k_each: int = 5) -> list[dict[str, Any]]:
        try:
            embedding = specter2_service.embed_text(query_text)
        except Exception as exc:
            logger.warning("Embedding generation unavailable for query_all: %s", exc)
            return []
        combined: list[dict[str, Any]] = []
        for collection_name in self.COLLECTIONS.values():
            try:
                collection = self._collection(collection_name)
                if collection.count() == 0:
                    continue
                result = collection.query(query_embeddings=[embedding], n_results=top_k_each)
            except Exception as exc:
                logger.warning("Chroma query failed for %s: %s", collection_name, exc)
                continue
            ids = result.get("ids", [[]])[0]
            distances = result.get("distances", [[]])[0]
            documents = result.get("documents", [[]])[0]
            metadatas = result.get("metadatas", [[]])[0]
            for record_id, distance, document, metadata in zip(ids, distances, documents, metadatas):
                combined.append(
                    {
                        "record_id": record_id,
                        "collection": collection_name,
                        "retrieval_score": max(0.0, min(1.0, 1.0 - float(distance or 1.0))),
                        "document": document or "",
                        "metadata": metadata or {},
                    }
                )
        combined.sort(key=lambda item: item["retrieval_score"], reverse=True)
        return combined


academic_index_service = AcademicIndexService()
