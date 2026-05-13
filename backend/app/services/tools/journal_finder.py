"""
Legacy journal finder adapter.

This module preserves the existing ``journal_finder.recommend()`` interface for
LLM/tool routing, but the retrieval backend now uses the academic index service.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.ingestion.index_service import academic_index_service
from app.services.journal_match.reranker import match_reranker

logger = logging.getLogger(__name__)


class JournalFinder:
    INTERNAL_PUBLISHERS = {
        "aira academic press",
        "open scholarship lab",
        "health policy analytics group",
        "societal analytics review",
        "clinical nlp consortium",
        "advanced computing materials",
        "scholarly data society",
        "earth systems informatics association",
        "reproducible systems community",
        "digital scholarship forum",
    }
    INTERNAL_TITLE_MARKERS = {
        "journal of responsible ai systems",
        "journal of computational publishing analytics",
        "journal of health data governance",
        "computational social science methods review",
    }
    INTERNAL_SOURCE_SLUGS = {
        "academic_seed",
        "bootstrap",
        "bootstrap-academic-seed",
        "demo",
        "fixture",
        "mock",
        "seed",
        "synthetic",
        "test",
    }
    SOURCE_TRUST_TIERS = {
        "clarivate_mjl": "verified_index",
        "scimago": "verified_rank",
        "scopus": "verified_index",
        "trusted-index": "verified_index",
    }
    PRODUCTION_TRUST_TIERS = {"verified_index", "verified_rank", "manual_verified_index"}
    STRICT_DOMAIN_MIN_FIT = {"network_security": 0.35, "health_policy": 0.35, "publishing_ai": 0.35}
    STRICT_DOMAIN_MIN_FIT.update({"cs_crypto_algorithms": 0.35})

    def __init__(self, use_ml: bool = True) -> None:
        self._use_ml = use_ml

    def recommend(
        self,
        abstract: str,
        title: str | None = None,
        top_k: int = 5,
        prefer_open_access: bool = False,
        min_impact_factor: float | None = None,
    ) -> list[dict[str, Any]]:
        query_text = "\n".join(part for part in [title or "", abstract] if part)
        try:
            rows = academic_index_service.query_all(query_text=query_text, top_k_each=max(top_k, 5))
        except Exception as exc:
            logger.warning("Legacy journal_finder query failed: %s", exc)
            return []
        recommendations: list[dict[str, Any]] = []
        for row in rows:
            metadata = row.get("metadata", {})
            if metadata.get("entity_type") != "venue" or str(metadata.get("venue_type") or "").lower() != "journal":
                continue
            if not self._is_production_eligible(metadata):
                continue
            if not self._domain_allowed(query_text, row):
                continue
            if str(metadata.get("publisher") or "").strip().lower() in self.INTERNAL_PUBLISHERS:
                continue
            if str(metadata.get("title") or "").strip().lower() in self.INTERNAL_TITLE_MARKERS:
                continue
            if prefer_open_access and not metadata.get("is_open_access", False):
                continue
            impact_factor = metadata.get("impact_factor")
            if min_impact_factor is not None and impact_factor is not None and float(impact_factor) < min_impact_factor:
                continue
            recommendations.append(
                {
                    "journal": metadata.get("title") or metadata.get("venue_id") or row.get("record_id"),
                    "entity_type": "venue",
                    "venue_id": metadata.get("venue_id"),
                    "venue_type": "journal",
                    "score": round(float(row.get("retrieval_score", 0.0)), 4),
                    "score_calibrated": False,
                    "reason": "Matched against indexed journal venue metadata in dữ liệu học thuật hiện có.",
                    "url": metadata.get("homepage_url") or metadata.get("source_url") or metadata.get("url"),
                    "publisher": metadata.get("publisher"),
                    "open_access": False,
                    "impact_factor": None,
                    "issn": None,
                    "h_index": None,
                    "review_time_weeks": None,
                    "acceptance_rate": None,
                    "domains": [item.strip() for item in str(metadata.get("subject_labels") or metadata.get("topic_tags") or "").split(",") if item.strip()],
                    "detected_domains": [],
                    "deadline": None,
                    "supporting_evidence": [],
                    "metric_provenance": {},
                    "unverified_metrics": [
                        key for key in ("impact_factor", "h_index", "avg_review_weeks", "acceptance_rate", "is_open_access")
                        if metadata.get(key) is not None
                    ],
                }
            )
            if len(recommendations) >= top_k:
                break
        return recommendations

    def _metadata_sources(self, metadata: dict[str, Any]) -> set[str]:
        raw_sources = metadata.get("source_ids") or metadata.get("source_names") or ""
        if isinstance(raw_sources, str):
            return {item.strip().lower() for item in raw_sources.split(",") if item.strip()}
        if isinstance(raw_sources, list):
            return {str(item).strip().lower() for item in raw_sources if str(item).strip()}
        return set()

    def _is_production_eligible(self, metadata: dict[str, Any]) -> bool:
        if metadata.get("production_eligible") is False:
            return False
        if not self._valid_title(str(metadata.get("title") or "")):
            return False
        subjects = metadata.get("subject_labels") or metadata.get("topic_tags")
        if isinstance(subjects, str):
            if not subjects.strip():
                return False
        elif not subjects:
            return False
        sources = self._metadata_sources(metadata)
        if not sources or sources & self.INTERNAL_SOURCE_SLUGS:
            return False
        trusted = [
            source
            for source in sources
            if self.SOURCE_TRUST_TIERS.get(source) in self.PRODUCTION_TRUST_TIERS
        ]
        return bool(trusted)

    def _valid_title(self, title: str) -> bool:
        title = title.strip()
        if len(title) < 6 or title.startswith("@"):
            return False
        if not re.search(r"[A-Za-z]", title):
            return False
        compact = re.sub(r"[^A-Za-z0-9]", "", title)
        return len(compact) >= 4

    def _domain_allowed(self, query_text: str, row: dict[str, Any]) -> bool:
        active_domains = match_reranker.active_domains(query_text)
        if not active_domains:
            return True
        domain_fit_score, _reasons = match_reranker._domain_fit(query_text, row)
        return all(domain_fit_score >= self.STRICT_DOMAIN_MIN_FIT.get(domain, 0.0) for domain in active_domains)

    @property
    def is_ml_enabled(self) -> bool:
        return self._use_ml

    @property
    def model_name(self) -> str:
        return str(academic_index_service.status()["embedding"]["model_name"])

    @property
    def collection_count(self) -> int:
        try:
            academic_index_service.ensure_collections()
            return sum(academic_index_service._collection(name).count() for name in academic_index_service.COLLECTIONS.values())
        except Exception:
            return 0


journal_finder = JournalFinder(use_ml=True)
