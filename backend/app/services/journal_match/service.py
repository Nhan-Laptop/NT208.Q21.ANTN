from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.academic_common import MatchRequestStatus
from app.models.crawl_source import CrawlSource
from app.models.entity_fingerprint import EntityFingerprint
from app.models.manuscript import Manuscript
from app.models.manuscript_assessment import ManuscriptAssessment
from app.models.match_candidate import MatchCandidate
from app.models.match_request import MatchRequest
from app.models.raw_source_snapshot import RawSourceSnapshot
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_subject import VenueSubject
from app.schemas.academic import MatchRequestCreate
from app.services.academic_policy import format_journal_match_summary
from app.services.file_service import file_service
from app.services.ingestion.index_service import academic_index_service
from app.services.journal_match.explainer import match_explainer
from app.services.journal_match.filters import match_filters
from app.services.journal_match.manuscript_parser import manuscript_parser
from app.services.journal_match.reranker import match_reranker
from app.services.journal_match.retriever import manuscript_retriever
from app.services.journal_match.topic_profile import ManuscriptTopicProfile
from crawler.connectors.source_registry import source_registry

logger = logging.getLogger(__name__)


class JournalMatchService:
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
    PRODUCTION_SOURCE_TYPES = {
        "conference_index",
        "conference_rank",
        "journal_directory",
        "journal_index",
        "journal_rank",
    }
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
    STRICT_DOMAIN_MIN_FIT = {
        "network_security": 0.35,
        "health_policy": 0.35,
        "publishing_ai": 0.35,
        "cs_crypto_algorithms": 0.35,
        "scientific_computing": 0.35,
        "food_studies": 0.35,
        "urban_studies": 0.35,
        "cultural_studies": 0.35,
        "asian_studies": 0.35,
        "tourism_studies": 0.35,
        "sociology_anthropology": 0.35,
        "environmental_studies": 0.35,
    }
    COMPUTING_BOOST_TERMS = {
        "python", "numpy", "matlab", "julia", "r-project",
        "programming", "software", "library", "toolkit",
        "framework", "repository", "open-source", "open source",
        "computational", "numerical", "computing", "computation",
        "simulation", "modelling", "modeling",
    }
    COMPUTING_BOOST_SUFFIX = "scientific software computational science numerical methods research software programming library toolkit"

    BOOK_SERIES_PATTERNS = [
        re.compile(r"^Advances in\b"),
        re.compile(r"^Lecture Notes in\b"),
        re.compile(r"^Studies in\b"),
        re.compile(r"^Topics in\b"),
        re.compile(r"^Foundations and Trends in\b"),
        re.compile(r"^Synthesis Lectures on\b"),
        re.compile(r"^SpringerBriefs in\b"),
    ]
    METRIC_FIELDS = {
        "impact_factor",
        "h_index",
        "avg_review_weeks",
        "acceptance_rate",
        "apc_usd",
        "sjr_quartile",
        "jcr_quartile",
        "citescore",
        "indexed_scopus",
        "indexed_wos",
        "is_open_access",
    }
    LOCAL_DATA_SOURCES = ["venues", "venue_subjects", "venue_metrics"]
    LOCAL_CONFIDENT_FLOOR = 0.10
    LOCAL_FALLBACK_FLOOR = 0.0
    MANUSCRIPT_FIELD_PATTERN = re.compile(
        r"(?im)^\s*(?:field|subject|subjects|lĩnh\s*vực|linh\s*vuc|chủ\s*đề|chu\s*de)\s*[:\-]\s*(.+)$"
    )
    TOKEN_STOPWORDS = {
        "abstract",
        "algorithm",
        "algorithms",
        "analysis",
        "and",
        "article",
        "based",
        "cho",
        "cua",
        "của",
        "data",
        "de",
        "field",
        "for",
        "from",
        "giai",
        "goi",
        "gợi",
        "hoc",
        "học",
        "keywords",
        "keyword",
        "linh",
        "lĩnh",
        "manuscript",
        "methods",
        "nghien",
        "nghiên",
        "paper",
        "study",
        "subject",
        "subjects",
        "summary",
        "tạp",
        "tap",
        "tiêu",
        "title",
        "tieu",
        "tom",
        "tóm",
        "tu",
        "từ",
        "vuc",
        "vực",
    }
    SUBJECT_EXPANSIONS = {
        "network security": [
            "cybersecurity",
            "information security",
            "computer networks",
            "computer science",
        ],
        "quantum": [
            "quantum computing",
            "quantum information",
            "quantum communication",
        ],
        "computer science": [
            "computing",
            "software",
            "information systems",
        ],
        "clinical informatics": [
            "medical informatics",
            "biomedical informatics",
            "health informatics",
        ],
        "health data governance": [
            "health informatics",
            "health policy",
            "data governance",
        ],
        "privacy": [
            "information privacy",
            "data protection",
            "security",
        ],
        "hospital data sharing": [
            "health information systems",
            "digital health",
        ],
    }
    SUBJECT_FALLBACK_LABELS = {
        "network security": [
            "Computer Science",
            "Engineering",
            "Physical Sciences",
        ],
        "quantum": [
            "Computer Science",
            "Engineering",
            "Physical Sciences",
            "Physics and Astronomy",
        ],
        "computer science": [
            "Computer Science",
            "Engineering",
            "Information Systems",
        ],
        "clinical informatics": [
            "Health Sciences",
            "Medicine",
            "Computer Science",
        ],
        "health data governance": [
            "Health Sciences",
            "Medicine",
            "Computer Science",
            "Decision Sciences",
            "Social Sciences",
        ],
        "privacy": [
            "Computer Science",
            "Engineering",
            "Social Sciences",
        ],
        "hospital data sharing": [
            "Health Sciences",
            "Medicine",
            "Computer Science",
            "Decision Sciences",
        ],
        "network_security": [
            "Computer Science",
            "Engineering",
            "Physical Sciences",
        ],
        "health_policy": [
            "Health Sciences",
            "Medicine",
            "Computer Science",
            "Decision Sciences",
            "Social Sciences",
        ],
        "scientific_computing": [
            "Computer Science",
            "Engineering",
            "Mathematics",
            "Physical Sciences",
        ],
        "cs_crypto_algorithms": [
            "Computer Science",
            "Engineering",
            "Mathematics",
            "Physical Sciences",
        ],
    }
    BROAD_SUBJECT_LABELS = {
        "computer science",
        "computing",
        "decision sciences",
        "engineering",
        "health sciences",
        "information systems",
        "mathematics",
        "medicine",
        "physical sciences",
        "physics and astronomy",
        "science",
        "social sciences",
    }

    @staticmethod
    def _enrich_query_for_computing(query_text: str) -> str:
        terms = set(re.findall(r"[a-z][a-z0-9\-]{2,}", query_text.lower()))
        if terms & JournalMatchService.COMPUTING_BOOST_TERMS:
            return query_text + "\n" + JournalMatchService.COMPUTING_BOOST_SUFFIX
        return query_text

    @staticmethod
    def _clean_phrase(value: str | None) -> str:
        cleaned = re.sub(r"\s+", " ", str(value or "").strip().lower())
        cleaned = re.sub(r"[^a-z0-9/&+\-\s]", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    @classmethod
    def _dedupe_phrases(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            cleaned = cls._clean_phrase(value)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            deduped.append(value.strip())
        return deduped

    @classmethod
    def _tokenize_text(cls, text: str) -> set[str]:
        tokens = {
            token
            for token in re.findall(r"[a-z][a-z0-9\-]{2,}", text.lower())
            if token not in cls.TOKEN_STOPWORDS
        }
        return tokens

    @classmethod
    def _token_overlap_score(cls, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        overlap = left & right
        if not overlap:
            return 0.0
        coverage = len(overlap) / max(len(left), 1)
        jaccard = len(overlap) / max(len(left | right), 1)
        return round(min(1.0, 0.7 * coverage + 0.3 * jaccard), 4)

    @classmethod
    def _phrase_similarity(cls, left: str, right: str) -> float:
        normalized_left = cls._clean_phrase(left)
        normalized_right = cls._clean_phrase(right)
        if not normalized_left or not normalized_right:
            return 0.0
        if normalized_left == normalized_right:
            return 1.0
        if normalized_left in normalized_right or normalized_right in normalized_left:
            return 0.85
        return cls._token_overlap_score(
            cls._tokenize_text(normalized_left),
            cls._tokenize_text(normalized_right),
        )

    @classmethod
    def _extract_field_values(cls, manuscript_text: str) -> list[str]:
        values: list[str] = []
        for match in cls.MANUSCRIPT_FIELD_PATTERN.finditer(manuscript_text or ""):
            values.extend(
                part.strip()
                for part in re.split(r"[;,/|\n]", match.group(1))
                if part.strip()
            )
        return cls._dedupe_phrases(values)

    @classmethod
    def _detect_subjects(
        cls,
        *,
        title: str | None,
        abstract: str | None,
        keywords: list[str],
        manuscript_text: str,
    ) -> list[str]:
        field_values = cls._extract_field_values(manuscript_text)
        combined_text = "\n".join(
            part
            for part in [
                title or "",
                abstract or "",
                " ".join(keywords),
                " ".join(field_values),
                manuscript_text[:3000],
            ]
            if part
        ).lower()
        detected: list[str] = []
        detected.extend(field_values)
        detected.extend(keyword for keyword in keywords if keyword and len(keyword.split()) <= 6)
        for phrase in cls.SUBJECT_EXPANSIONS:
            if phrase in combined_text:
                detected.append(phrase)
        for domain_label in match_reranker.inferred_domain_labels(combined_text):
            if domain_label:
                detected.append(domain_label)
        return cls._dedupe_phrases(detected)

    @classmethod
    def _expand_subjects(cls, detected_subjects: list[str], manuscript_text: str) -> list[str]:
        expanded: list[str] = list(detected_subjects)
        normalized_detected = [cls._clean_phrase(subject) for subject in detected_subjects]
        for normalized_subject in normalized_detected:
            for phrase, phrase_expansions in cls.SUBJECT_EXPANSIONS.items():
                if phrase in normalized_subject or normalized_subject in phrase:
                    expanded.extend(phrase_expansions)
                    expanded.extend(cls.SUBJECT_FALLBACK_LABELS.get(phrase, []))
        for domain_name in match_reranker.active_domains(manuscript_text):
            expanded.extend(cls.SUBJECT_FALLBACK_LABELS.get(domain_name, []))
        return cls._dedupe_phrases(expanded)

    @classmethod
    def _is_broad_subject_phrase(cls, value: str | None) -> bool:
        normalized = cls._clean_phrase(value)
        return normalized in cls.BROAD_SUBJECT_LABELS

    def _build_local_match_profile(
        self,
        *,
        manuscript: Manuscript,
        topic_profile: ManuscriptTopicProfile,
        manuscript_text: str,
    ) -> dict[str, Any]:
        extracted_keywords = [
            str(keyword).strip()
            for keyword in (manuscript.keywords_json or [])
            if str(keyword).strip()
        ]
        extracted_title = (manuscript.title or topic_profile.title or "").strip() or None
        detected_subjects = self._detect_subjects(
            title=extracted_title,
            abstract=manuscript.abstract or topic_profile.abstract,
            keywords=extracted_keywords,
            manuscript_text=manuscript.body_text or manuscript_text,
        )
        expanded_subjects = self._expand_subjects(detected_subjects, manuscript_text)
        phrase_candidates = self._dedupe_phrases(
            [
                value
                for value in [
                    extracted_title or "",
                    *extracted_keywords,
                    *detected_subjects,
                    *expanded_subjects,
                    topic_profile.research_field.replace("_", " ") if topic_profile.research_field else "",
                ]
                if value
            ]
        )
        specific_search_phrases: list[str] = []
        broad_search_phrases: list[str] = []
        for value in phrase_candidates:
            if self._is_broad_subject_phrase(value):
                broad_search_phrases.append(value.strip())
            else:
                specific_search_phrases.append(value.strip())
        specific_tokens = sorted(
            self._tokenize_text(
                " ".join(
                    [
                        extracted_title or "",
                        " ".join(extracted_keywords),
                        " ".join(specific_search_phrases),
                    ]
                )
            ),
            key=lambda token: (-len(token), token),
        )
        broad_tokens = sorted(
            self._tokenize_text(" ".join(broad_search_phrases)),
            key=lambda token: (-len(token), token),
        )
        query_tokens = sorted(
            self._tokenize_text(
                " ".join(
                    [
                        manuscript_text[:3000],
                        " ".join(extracted_keywords),
                        " ".join(expanded_subjects),
                    ]
                )
            ),
            key=lambda token: (-len(token), token),
        )
        return {
            "extracted_title": extracted_title,
            "extracted_keywords": extracted_keywords,
            "detected_subjects": detected_subjects,
            "expanded_subjects": expanded_subjects,
            "search_phrases": phrase_candidates[:20],
            "search_tokens": query_tokens[:18],
            "specific_search_phrases": specific_search_phrases[:18],
            "broad_search_phrases": broad_search_phrases[:12],
            "specific_search_tokens": specific_tokens[:18],
            "broad_search_tokens": broad_tokens[:12],
        }

    @staticmethod
    def _latest_venue_metric(venue: Venue) -> Any | None:
        ordered = sorted(
            venue.metrics,
            key=lambda metric: (metric.metric_year or 0, metric.updated_at),
            reverse=True,
        )
        return ordered[0] if ordered else None

    @staticmethod
    def _stringify_metadata(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, list):
            return ", ".join(str(item) for item in value if item is not None)
        if isinstance(value, (str, bool, int, float)):
            return value
        return str(value)

    def _build_local_venue_snapshot(self, venue: Venue) -> tuple[str, dict[str, Any]]:
        metric = self._latest_venue_metric(venue)
        subject_labels = [subject.label for subject in venue.subjects if subject.label]
        policy_notes = " ".join(policy.notes or "" for policy in venue.policies if policy.notes)
        source_ids = sorted({metric_row.source_id for metric_row in venue.metrics if metric_row.source_id})
        metric_names = sorted({metric_row.metric_name for metric_row in venue.metrics if metric_row.metric_name})
        document = " ".join(
            part
            for part in [
                f"Journal: {venue.title}" if str(venue.venue_type.value).lower() == "journal" else f"Venue: {venue.title}",
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
        metadata = {
            "entity_type": "venue",
            "venue_id": venue.id,
            "venue_type": venue.venue_type.value,
            "title": venue.title,
            "publisher": venue.publisher,
            "homepage_url": venue.homepage_url,
            "source_url": venue.source_url,
            "subject_labels": subject_labels,
            "source_ids": source_ids,
            "source_names": source_ids,
            "issn": venue.issn_print,
            "eissn": venue.issn_electronic,
            "metric_names": metric_names,
            "provenance_hash": "|".join(source_ids + metric_names) or venue.id,
            "sjr_quartile": metric.sjr_quartile if metric else None,
            "jcr_quartile": metric.jcr_quartile if metric else None,
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
            "embedding_model": "local-venue-metadata",
            "last_indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        return document, {
            key: value
            for key, raw_value in metadata.items()
            if (value := self._stringify_metadata(raw_value)) is not None
        }

    @staticmethod
    def _safe_http_url(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        url = value.strip()
        if not url or not re.match(r"^https?://", url, flags=re.IGNORECASE):
            return None
        return url

    @staticmethod
    def _normalize_issn(value: Any) -> str | None:
        raw = re.sub(r"[^0-9Xx]", "", str(value or ""))
        if len(raw) != 8:
            return None
        normalized = raw.upper()
        return f"{normalized[:4]}-{normalized[4:]}"

    @staticmethod
    def _source_link_label(url: str, source_name: str | None = None) -> tuple[str, str]:
        lowered = url.lower()
        if "portal.issn.org" in lowered:
            return "ISSN Portal", "issn_portal"
        if "scimagojr.com" in lowered:
            return "SJR page", "sjr"
        if source_name:
            label = source_name.replace("_", " ").strip() or "Source page"
            return label, "source"
        return "Source page", "source"

    @classmethod
    def _append_trusted_link(
        cls,
        links: list[dict[str, str]],
        seen_urls: set[str],
        *,
        label: str,
        url: Any,
        link_type: str,
    ) -> None:
        safe_url = cls._safe_http_url(url)
        if safe_url is None:
            return
        key = safe_url.rstrip("/").lower()
        if key in seen_urls:
            return
        seen_urls.add(key)
        links.append({"label": label, "url": safe_url, "type": link_type})

    @classmethod
    def build_trusted_venue_links(cls, metadata: dict[str, Any]) -> tuple[list[dict[str, str]], str | None, str | None]:
        links: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        homepage_url = cls._safe_http_url(metadata.get("homepage_url"))
        source_url = cls._safe_http_url(metadata.get("source_url"))
        if homepage_url:
            cls._append_trusted_link(links, seen_urls, label="Journal home", url=homepage_url, link_type="homepage")
        if source_url:
            label, link_type = cls._source_link_label(source_url)
            cls._append_trusted_link(links, seen_urls, label=label, url=source_url, link_type=link_type)

        for source_detail in (metadata.get("source_details") or [])[:4]:
            if not isinstance(source_detail, dict):
                continue
            official_reference = cls._safe_http_url(source_detail.get("official_source_reference"))
            if official_reference is None:
                continue
            label, link_type = cls._source_link_label(
                official_reference,
                source_name=str(source_detail.get("source_name") or "").strip() or None,
            )
            cls._append_trusted_link(links, seen_urls, label=label, url=official_reference, link_type=link_type)

        for issn_label, raw_issn in (("ISSN", metadata.get("issn")), ("eISSN", metadata.get("eissn"))):
            normalized_issn = cls._normalize_issn(raw_issn)
            if normalized_issn is None:
                continue
            cls._append_trusted_link(
                links,
                seen_urls,
                label=f"{issn_label} Portal",
                url=f"https://portal.issn.org/resource/ISSN/{normalized_issn}",
                link_type="issn_portal",
            )

        link_warning: str | None = None
        if not links:
            link_warning = "Chua co lien ket da xac minh trong metadata venue hien co."
        elif not (homepage_url or source_url):
            link_warning = "Chi co lien ket chi muc hoac ISSN; chua luu duoc homepage journal rieng."
        primary_url = links[0]["url"] if links else None
        return links, primary_url, link_warning

    def _collect_stage_ids(
        self,
        db: Session,
        *,
        desired_type: str,
        specific_search_phrases: list[str],
        broad_search_phrases: list[str],
        specific_search_tokens: list[str],
        broad_search_tokens: list[str],
        top_k: int,
    ) -> tuple[set[str], set[str], set[str], set[str]]:
        normalized_specific_phrases = [
            self._clean_phrase(phrase)
            for phrase in specific_search_phrases
            if self._clean_phrase(phrase)
        ]
        normalized_broad_phrases = [
            self._clean_phrase(phrase)
            for phrase in broad_search_phrases
            if self._clean_phrase(phrase)
        ]
        exact_ids: set[str] = set()
        fuzzy_ids: set[str] = set()
        semantic_ids: set[str] = set()
        broad_ids: set[str] = set()

        if normalized_specific_phrases:
            exact_rows = (
                db.query(VenueSubject.venue_id)
                .join(Venue, Venue.id == VenueSubject.venue_id)
                .filter(
                    Venue.active.is_(True),
                    func.lower(Venue.venue_type) == desired_type,
                    func.lower(VenueSubject.label).in_(normalized_specific_phrases[:12]),
                )
                .limit(max(60, top_k * 20))
                .all()
            )
            exact_ids.update(row[0] for row in exact_rows if row[0])

            text_phrase_clauses = []
            for phrase in normalized_specific_phrases[:10]:
                if len(phrase) < 4:
                    continue
                pattern = f"%{phrase}%"
                text_phrase_clauses.extend(
                    [
                        func.lower(Venue.title).like(pattern),
                        func.lower(Venue.canonical_title).like(pattern),
                        func.lower(Venue.publisher).like(pattern),
                        func.lower(Venue.aims_scope).like(pattern),
                    ]
                )
            if text_phrase_clauses:
                exact_text_rows = (
                    db.query(Venue.id)
                    .filter(
                        Venue.active.is_(True),
                        func.lower(Venue.venue_type) == desired_type,
                        or_(*text_phrase_clauses),
                    )
                    .limit(max(80, top_k * 24))
                    .all()
                )
                exact_ids.update(row[0] for row in exact_text_rows if row[0])

        fuzzy_subject_clauses = []
        for phrase in normalized_specific_phrases[:10]:
            if len(phrase) >= 4:
                fuzzy_subject_clauses.append(func.lower(VenueSubject.label).like(f"%{phrase}%"))
        for token in specific_search_tokens[:10]:
            fuzzy_subject_clauses.append(func.lower(VenueSubject.label).like(f"%{token.lower()}%"))
        if fuzzy_subject_clauses:
            fuzzy_rows = (
                db.query(VenueSubject.venue_id)
                .join(Venue, Venue.id == VenueSubject.venue_id)
                .filter(
                    Venue.active.is_(True),
                    func.lower(Venue.venue_type) == desired_type,
                    or_(*fuzzy_subject_clauses),
                )
                .limit(max(120, top_k * 30))
                .all()
            )
            fuzzy_ids.update(row[0] for row in fuzzy_rows if row[0])

        semantic_clauses = []
        semantic_tokens = list(dict.fromkeys([*specific_search_tokens[:12], *broad_search_tokens[:6]]))
        for token in semantic_tokens:
            pattern = f"%{token.lower()}%"
            semantic_clauses.extend(
                [
                    func.lower(Venue.title).like(pattern),
                    func.lower(Venue.canonical_title).like(pattern),
                    func.lower(Venue.publisher).like(pattern),
                    func.lower(Venue.aims_scope).like(pattern),
                    func.lower(VenueSubject.label).like(pattern),
                ]
            )
        if semantic_clauses:
            semantic_rows = (
                db.query(Venue.id)
                .outerjoin(VenueSubject, VenueSubject.venue_id == Venue.id)
                .filter(
                    Venue.active.is_(True),
                    func.lower(Venue.venue_type) == desired_type,
                    or_(*semantic_clauses),
                )
                .distinct()
                .limit(max(150, top_k * 36))
                .all()
            )
            semantic_ids.update(row[0] for row in semantic_rows if row[0])

        if normalized_broad_phrases:
            broad_exact_rows = (
                db.query(VenueSubject.venue_id)
                .join(Venue, Venue.id == VenueSubject.venue_id)
                .filter(
                    Venue.active.is_(True),
                    func.lower(Venue.venue_type) == desired_type,
                    func.lower(VenueSubject.label).in_(normalized_broad_phrases[:12]),
                )
                .limit(max(80, top_k * 24))
                .all()
            )
            broad_ids.update(row[0] for row in broad_exact_rows if row[0])

        broad_subject_clauses = []
        for phrase in normalized_broad_phrases[:10]:
            if len(phrase) >= 4:
                broad_subject_clauses.append(func.lower(VenueSubject.label).like(f"%{phrase}%"))
        for token in broad_search_tokens[:8]:
            broad_subject_clauses.append(func.lower(VenueSubject.label).like(f"%{token.lower()}%"))
        if broad_subject_clauses:
            broad_rows = (
                db.query(VenueSubject.venue_id)
                .join(Venue, Venue.id == VenueSubject.venue_id)
                .filter(
                    Venue.active.is_(True),
                    func.lower(Venue.venue_type) == desired_type,
                    or_(*broad_subject_clauses),
                )
                .limit(max(120, top_k * 30))
                .all()
            )
            broad_ids.update(row[0] for row in broad_rows if row[0])

        if not (exact_ids or fuzzy_ids or semantic_ids or broad_ids) and normalized_broad_phrases:
            semantic_ids.update(broad_ids)

        return exact_ids, fuzzy_ids, semantic_ids, broad_ids

    def _score_local_venue_candidate(
        self,
        *,
        venue: Venue,
        manuscript_tokens: set[str],
        specific_search_phrases: list[str],
        broad_search_phrases: list[str],
        specific_query_tokens: set[str],
        broad_query_tokens: set[str],
        exact_ids: set[str],
        fuzzy_ids: set[str],
        semantic_ids: set[str],
        broad_ids: set[str],
    ) -> tuple[float, dict[str, Any]]:
        subject_labels = [subject.label for subject in venue.subjects if subject.label]
        normalized_subjects = [self._clean_phrase(label) for label in subject_labels]
        candidate_blob = " ".join(
            part
            for part in [
                venue.title,
                venue.canonical_title,
                venue.publisher or "",
                venue.aims_scope or "",
                " ".join(subject_labels),
            ]
            if part
        )
        candidate_tokens = self._tokenize_text(candidate_blob)
        normalized_blob = self._clean_phrase(candidate_blob)

        specific_subject_matches = sum(
            1 for phrase in specific_search_phrases if self._clean_phrase(phrase) in normalized_subjects
        )
        specific_text_matches = sum(
            1
            for phrase in specific_search_phrases
            if self._clean_phrase(phrase) and self._clean_phrase(phrase) in normalized_blob
        )
        specific_exact_score = min(1.0, 0.45 * min(specific_subject_matches, 2) + 0.20 * min(specific_text_matches, 2))

        broad_subject_matches = sum(
            1 for phrase in broad_search_phrases if self._clean_phrase(phrase) in normalized_subjects
        )
        broad_text_matches = sum(
            1
            for phrase in broad_search_phrases
            if self._clean_phrase(phrase) and self._clean_phrase(phrase) in normalized_blob
        )
        broad_exact_score = min(1.0, 0.25 * min(broad_subject_matches, 2) + 0.10 * min(broad_text_matches, 1))

        specific_fuzzy_subject_score = 0.0
        for phrase in specific_search_phrases:
            for label in subject_labels:
                specific_fuzzy_subject_score = max(specific_fuzzy_subject_score, self._phrase_similarity(phrase, label))

        broad_fuzzy_subject_score = 0.0
        for phrase in broad_search_phrases:
            for label in subject_labels:
                broad_fuzzy_subject_score = max(broad_fuzzy_subject_score, self._phrase_similarity(phrase, label))

        semantic_score = self._token_overlap_score(specific_query_tokens, candidate_tokens)
        broad_semantic_score = self._token_overlap_score(broad_query_tokens, candidate_tokens)
        scope_score = self._token_overlap_score(manuscript_tokens, candidate_tokens)
        has_specific_signal = bool(
            specific_subject_matches
            or specific_text_matches
            or specific_fuzzy_subject_score >= 0.45
            or semantic_score >= 0.12
        )
        has_broad_signal = bool(
            broad_subject_matches
            or broad_text_matches
            or broad_fuzzy_subject_score >= 0.45
            or broad_semantic_score >= 0.12
        )
        broad_subject_only = bool(has_broad_signal and not has_specific_signal)

        stage_names: list[str] = []
        stage_score = 0.0
        if venue.id in exact_ids:
            stage_names.append("exact")
            stage_score = max(stage_score, 0.58)
        if venue.id in fuzzy_ids:
            stage_names.append("fuzzy")
            stage_score = max(stage_score, 0.38)
        if venue.id in semantic_ids:
            stage_names.append("semantic")
            stage_score = max(stage_score, 0.22)
        if venue.id in broad_ids:
            stage_names.append("broad")
            stage_score = max(stage_score, 0.12)

        indexed_bonus = 0.05 if venue.indexed_scopus or venue.indexed_wos else 0.0
        blended_score = (
            0.40 * specific_exact_score
            + 0.22 * specific_fuzzy_subject_score
            + 0.15 * semantic_score
            + 0.08 * scope_score
            + 0.05 * broad_exact_score
            + 0.04 * broad_fuzzy_subject_score
            + 0.01 * broad_semantic_score
            + indexed_bonus
        )
        if broad_subject_only and specific_query_tokens:
            blended_score = min(blended_score, 0.24)
        retrieval_score = min(
            1.0,
            max(
                stage_score,
                blended_score,
            ),
        )
        return round(retrieval_score, 4), {
            "local_match_stage": stage_names or ["semantic"],
            "local_exact_score": round(specific_exact_score, 4),
            "local_fuzzy_score": round(specific_fuzzy_subject_score, 4),
            "local_semantic_score": round(semantic_score, 4),
            "local_scope_score": round(scope_score, 4),
            "local_broad_score": round(max(broad_exact_score, broad_fuzzy_subject_score, broad_semantic_score), 4),
            "broad_subject_only": broad_subject_only,
        }

    def _retrieve_local_venue_candidates(
        self,
        db: Session,
        *,
        request: MatchRequest,
        manuscript_text: str,
        topic_profile: ManuscriptTopicProfile,
        manuscript: Manuscript,
        top_k: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        desired_type = str(request.desired_venue_type or "journal").lower()
        match_profile = self._build_local_match_profile(
            manuscript=manuscript,
            topic_profile=topic_profile,
            manuscript_text=manuscript_text,
        )
        specific_search_phrases = match_profile["specific_search_phrases"]
        broad_search_phrases = match_profile["broad_search_phrases"]
        specific_search_tokens = match_profile["specific_search_tokens"]
        broad_search_tokens = match_profile["broad_search_tokens"]
        exact_ids, fuzzy_ids, semantic_ids, broad_ids = self._collect_stage_ids(
            db,
            desired_type=desired_type,
            specific_search_phrases=specific_search_phrases,
            broad_search_phrases=broad_search_phrases,
            specific_search_tokens=specific_search_tokens,
            broad_search_tokens=broad_search_tokens,
            top_k=top_k,
        )
        combined_ids = exact_ids | fuzzy_ids | semantic_ids | broad_ids
        if not combined_ids:
            return [], {
                **match_profile,
                "candidate_count_before_filter": 0,
                "candidate_count_after_filter": 0,
                "data_sources_used": list(self.LOCAL_DATA_SOURCES),
                "local_venue_count": 0,
            }

        venues = (
            db.query(Venue)
            .options(selectinload(Venue.subjects), selectinload(Venue.metrics), selectinload(Venue.policies))
            .filter(Venue.id.in_(combined_ids))
            .all()
        )
        manuscript_tokens = self._tokenize_text(manuscript_text)
        specific_query_tokens = set(specific_search_tokens)
        broad_query_tokens = set(broad_search_tokens)
        scored_candidates: list[tuple[float, dict[str, Any]]] = []
        for venue in venues:
            if str(venue.venue_type.value).lower() != desired_type:
                continue
            retrieval_score, local_breakdown = self._score_local_venue_candidate(
                venue=venue,
                manuscript_tokens=manuscript_tokens,
                specific_search_phrases=specific_search_phrases,
                broad_search_phrases=broad_search_phrases,
                specific_query_tokens=specific_query_tokens,
                broad_query_tokens=broad_query_tokens,
                exact_ids=exact_ids,
                fuzzy_ids=fuzzy_ids,
                semantic_ids=semantic_ids,
                broad_ids=broad_ids,
            )
            if retrieval_score <= 0.0:
                continue
            document, metadata = self._build_local_venue_snapshot(venue)
            metadata.update(local_breakdown)
            scored_candidates.append(
                (
                    retrieval_score,
                    {
                        "record_id": f"venue:{venue.id}",
                        "collection": "local_venues",
                        "retrieval_score": retrieval_score,
                        "document": document,
                        "metadata": metadata,
                    },
                )
            )

        scored_candidates.sort(
            key=lambda item: (
                item[0],
                item[1]["metadata"].get("local_exact_score", 0.0),
                item[1]["metadata"].get("local_fuzzy_score", 0.0),
                item[1]["metadata"].get("local_semantic_score", 0.0),
                int(not bool(item[1]["metadata"].get("broad_subject_only"))),
                item[1]["metadata"].get("title") or "",
            ),
            reverse=True,
        )
        local_candidates = [candidate for _score, candidate in scored_candidates[: max(50, top_k * 8)]]
        return local_candidates, {
            **match_profile,
            "candidate_count_before_filter": len(local_candidates),
            "candidate_count_after_filter": len(local_candidates),
            "data_sources_used": list(self.LOCAL_DATA_SOURCES),
            "local_venue_count": len(local_candidates),
        }

    @staticmethod
    def _merge_candidates(*candidate_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for group in candidate_groups:
            for candidate in group:
                record_id = str(candidate.get("record_id") or "")
                if not record_id:
                    continue
                previous = merged.get(record_id)
                if previous is None or float(candidate.get("retrieval_score") or 0.0) > float(previous.get("retrieval_score") or 0.0):
                    merged[record_id] = candidate
        return sorted(
            merged.values(),
            key=lambda item: float(item.get("retrieval_score") or 0.0),
            reverse=True,
        )

    @staticmethod
    def _confidence_label(best_score: float | None) -> str | None:
        if best_score is None:
            return None
        if best_score >= 0.70:
            return "high"
        if best_score >= 0.40:
            return "medium"
        return "low"

    @staticmethod
    def _subject_compatibility_check(manuscript_text: str, metadata: dict[str, Any]) -> list[str]:
        subject_labels = metadata.get("subject_labels") or metadata.get("topic_tags") or ""
        if isinstance(subject_labels, str):
            venue_subjects = set(re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", subject_labels.lower()))
        elif isinstance(subject_labels, (list, tuple)):
            venue_subjects = set()
            for item in subject_labels:
                venue_subjects.update(re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", str(item).lower()))
        else:
            venue_subjects = set()
        if not venue_subjects:
            return ["venue_has_no_subjects"]
        manuscript_terms = set(re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", manuscript_text.lower()))
        biomedical = {"medicine", "clinical", "patient", "disease", "surgery", "oncology", "cardiology"}
        astronomy = {"astronomy", "astrophysics", "cosmology", "galaxy", "telescope", "black-hole"}
        social = {"anthropology", "sociology", "cultural", "ethnographic", "qualitative", "community"}
        food = {"food", "cuisine", "culinary", "gastronomy", "nutrition"}
        urban = {"urban", "city", "sidewalk", "neighborhood", "municipal"}
        computing = {"python", "numpy", "programming", "software", "algorithm", "computational", "numerical"}

        manuscript_field = None
        if manuscript_terms & computing:
            manuscript_field = "computing"
        elif manuscript_terms & food:
            manuscript_field = "food"
        elif manuscript_terms & urban:
            manuscript_field = "urban"
        elif manuscript_terms & biomedical:
            manuscript_field = "biomedical"
        elif manuscript_terms & astronomy:
            manuscript_field = "astronomy"
        elif manuscript_terms & social:
            manuscript_field = "social"

        if manuscript_field == "computing" and not (venue_subjects & computing) and not (venue_subjects & {"science", "mathematics", "engineering", "data", "information"}):
            return ["computing_manuscript_mismatches_venue_subjects"]
        if manuscript_field == "food" and not (venue_subjects & food) and not (venue_subjects & {"culture", "urban", "social", "anthropology", "tourism"}):
            return ["food_manuscript_mismatches_venue_subjects"]
        if manuscript_field == "urban" and not (venue_subjects & urban) and not (venue_subjects & {"culture", "social", "geography", "planning", "architecture"}):
            return ["urban_manuscript_mismatches_venue_subjects"]
        return []

    @staticmethod
    def _detect_warning_flags(venue: Venue) -> list[str]:
        flags: list[str] = []
        title = (venue.title or "").strip()
        for pattern in JournalMatchService.BOOK_SERIES_PATTERNS:
            if pattern.search(title):
                flags.append("suspected_book_series")
                break
        if str(venue.venue_type.value).lower() == "conference" and "proceedings" in title.lower():
            flags.append("conference_proceedings")
        return flags

    def create_manuscript(
        self,
        db: Session,
        *,
        current_user: User,
        text: str,
        session_id: str | None = None,
        file_attachment_id: str | None = None,
        title: str | None = None,
        source_type: str = "text",
    ) -> tuple[Manuscript, ManuscriptAssessment]:
        if not (text or "").strip():
            raise HTTPException(status_code=400, detail="Manuscript text is empty.")
        parsed = manuscript_parser.parse(text, title=title)
        assessment_payload = manuscript_parser.assess(parsed)
        manuscript = Manuscript(
            user_id=current_user.id,
            session_id=session_id,
            file_attachment_id=file_attachment_id,
            title=parsed.get("title"),
            abstract=parsed.get("abstract"),
            body_text=parsed.get("body_text") or text,
            keywords_json=parsed.get("keywords"),
            references_json=parsed.get("references"),
            parsed_structure=parsed.get("structure"),
            source_type=source_type,
        )
        db.add(manuscript)
        db.flush()
        assessment = ManuscriptAssessment(manuscript_id=manuscript.id, **assessment_payload)
        db.add(assessment)
        db.commit()
        db.refresh(manuscript)
        db.refresh(assessment)
        return manuscript, assessment

    def create_manuscript_from_file(
        self,
        db: Session,
        *,
        current_user: User,
        session_id: str,
        file_id: str,
        title: str | None = None,
    ) -> tuple[Manuscript, ManuscriptAssessment]:
        attachment = file_service.get_attachment(db=db, current_user=current_user, session_id=session_id, file_id=file_id)
        if not attachment.extracted_text:
            raise HTTPException(status_code=400, detail="Uploaded file does not contain extractable text.")
        return self.create_manuscript(
            db,
            current_user=current_user,
            text=attachment.extracted_text,
            session_id=session_id,
            file_attachment_id=attachment.id,
            title=title or attachment.file_name,
            source_type="file_attachment",
        )

    def _resolve_or_create_manuscript(
        self,
        db: Session,
        *,
        current_user: User,
        payload: MatchRequestCreate,
    ) -> tuple[Manuscript, ManuscriptAssessment | None]:
        if payload.manuscript_id:
            manuscript = db.query(Manuscript).filter(Manuscript.id == payload.manuscript_id, Manuscript.user_id == current_user.id).first()
            if manuscript is None:
                raise HTTPException(status_code=404, detail="Manuscript not found.")
            assessment = (
                db.query(ManuscriptAssessment)
                .filter(ManuscriptAssessment.manuscript_id == manuscript.id)
                .first()
            )
            return manuscript, assessment
        if payload.file_id and payload.session_id:
            return self.create_manuscript_from_file(
                db,
                current_user=current_user,
                session_id=payload.session_id,
                file_id=payload.file_id,
                title=payload.title,
            )
        if payload.text:
            return self.create_manuscript(
                db,
                current_user=current_user,
                text=payload.text,
                session_id=payload.session_id,
                title=payload.title,
                source_type="text_input",
            )
        raise HTTPException(status_code=400, detail="Provide manuscript_id or file_id/session_id or text.")

    def create_match_request(
        self,
        db: Session,
        *,
        current_user: User,
        payload: MatchRequestCreate,
    ) -> MatchRequest:
        manuscript, assessment = self._resolve_or_create_manuscript(db, current_user=current_user, payload=payload)
        request = MatchRequest(
            manuscript_id=manuscript.id,
            user_id=current_user.id,
            desired_venue_type=payload.desired_venue_type.lower() if payload.desired_venue_type else "journal",
            min_quartile=payload.min_quartile.upper() if payload.min_quartile else None,
            require_scopus=payload.require_scopus,
            require_wos=payload.require_wos,
            apc_budget_usd=payload.apc_budget_usd,
            max_review_weeks=payload.max_review_weeks,
            include_cfps=payload.include_cfps,
            request_payload={
                "title": payload.title,
                "top_k": payload.top_k,
                "manuscript_id": manuscript.id,
                "assessment_id": assessment.id if assessment else None,
            },
        )
        db.add(request)
        db.commit()
        db.refresh(request)
        return request

    def run_request(self, db: Session, *, current_user: User, request_id: str) -> MatchRequest:
        request = db.query(MatchRequest).filter(MatchRequest.id == request_id, MatchRequest.user_id == current_user.id).first()
        if request is None:
            raise HTTPException(status_code=404, detail="Match request not found.")
        manuscript = db.query(Manuscript).filter(Manuscript.id == request.manuscript_id).first()
        assessment = (
            db.query(ManuscriptAssessment)
            .filter(ManuscriptAssessment.manuscript_id == request.manuscript_id)
            .first()
        )
        if manuscript is None:
            raise HTTPException(status_code=404, detail="Manuscript for match request not found.")

        request.status = MatchRequestStatus.RUNNING
        db.add(request)
        db.commit()

        try:
            manuscript_text_full = "\n".join(part for part in [manuscript.title or "", manuscript.abstract or "", manuscript.body_text[:6000]] if part)
            topic_profile = ManuscriptTopicProfile(
                title=manuscript.title,
                abstract=manuscript.abstract,
                keywords=list(manuscript.keywords_json) if manuscript.keywords_json and isinstance(manuscript.keywords_json, list) else [],
                body_text=manuscript.body_text,
            )
            query_text = self._enrich_query_for_computing(topic_profile.build_embedding_query())
            top_k = int((request.request_payload or {}).get("top_k", 10))
            local_candidates, local_diagnostics = self._retrieve_local_venue_candidates(
                db,
                request=request,
                manuscript_text=manuscript_text_full,
                topic_profile=topic_profile,
                manuscript=manuscript,
                top_k=top_k,
            )
            retrieved: list[dict[str, Any]] = []
            retriever_error: str | None = None
            try:
                retrieved = manuscript_retriever.retrieve(query_text=query_text, top_k_each=max(5, min(top_k, 10)))
            except Exception as exc:
                retriever_error = f"{exc.__class__.__name__}: {exc}"
                logger.warning("Optional journal_match retriever failed for request %s: %s", request.id, exc)
            if not request.include_cfps:
                retrieved = [candidate for candidate in retrieved if candidate.get("metadata", {}).get("entity_type") != "cfp"]
            combined_candidates = self._merge_candidates(local_candidates, retrieved)
            filtered, diagnostics = match_filters.apply(request, combined_candidates)
            finalized, final_diagnostics = self._finalize_primary_candidates(db, request=request, manuscript_text=manuscript_text_full, candidates=filtered)
            readiness = assessment.readiness_score if assessment else 0.5
            ranked = match_reranker.rerank(
                request=request,
                manuscript_text=manuscript_text_full,
                readiness_score=readiness,
                candidates=finalized[: top_k * 3],
            )

            existing_candidates = (
                db.query(MatchCandidate)
                .filter(MatchCandidate.match_request_id == request.id)
                .all()
            )
            replaced_candidate_count = len(existing_candidates)
            for existing in existing_candidates:
                db.delete(existing)
            db.flush()
            db.expire(request, ["candidates"])

            manuscript_has_content = readiness >= 0.35
            quality_candidates = [candidate for candidate in ranked if candidate["final_score"] >= self.LOCAL_CONFIDENT_FLOOR][:top_k]
            if not quality_candidates and manuscript_has_content and local_diagnostics.get("local_venue_count", 0) > 0:
                quality_candidates = [
                    candidate
                    for candidate in ranked
                    if candidate["final_score"] >= self.LOCAL_FALLBACK_FLOOR
                ][: max(1, min(top_k, 3))]

            for candidate in quality_candidates:
                metadata = candidate.get("metadata", {})
                explanation = match_explainer.build(candidate, manuscript_text=manuscript_text_full)
                breakdown = candidate["score_breakdown"]
                match_candidate = MatchCandidate(
                    match_request_id=request.id,
                    entity_type=str(metadata.get("entity_type") or "venue"),
                    venue_id=metadata.get("venue_id"),
                    cfp_event_id=metadata.get("cfp_event_id"),
                    article_id=metadata.get("article_id"),
                    rank=candidate["rank"],
                    retrieval_score=breakdown["retrieval_score"],
                    scope_overlap_score=breakdown["scope_overlap_score"],
                    quality_fit_score=breakdown["quality_fit_score"],
                    policy_fit_score=breakdown["policy_fit_score"],
                    freshness_score=breakdown["freshness_score"],
                    manuscript_readiness_score=breakdown["manuscript_readiness_score"],
                    penalty_score=breakdown["penalty_score"],
                    final_score=breakdown["final_score"],
                    explanation_payload=explanation,
                    evidence_payload={"metadata": metadata, "document": candidate.get("document")},
                )
                db.add(match_candidate)

            request.status = MatchRequestStatus.SUCCEEDED
            request.executed_at = datetime.now(timezone.utc)
            detected_domain = match_reranker.inferred_domain_labels(query_text)
            match_status = (
                "matched" if quality_candidates else
                ("missing_manuscript_info" if not manuscript_has_content else "insufficient_corpus")
            )
            best_score = float(quality_candidates[0]["final_score"]) if quality_candidates else None
            confidence = self._confidence_label(best_score)
            broad_only_top_matches = bool(quality_candidates) and all(
                bool((candidate.get("metadata", {}) or {}).get("broad_subject_only"))
                for candidate in quality_candidates[: min(len(quality_candidates), 3)]
            )
            if broad_only_top_matches and quality_candidates:
                confidence = "low"
            retrieved_entity_types = {
                str(candidate.get("metadata", {}).get("entity_type") or "").lower()
                for candidate in retrieved
            }
            data_sources_used = list(self.LOCAL_DATA_SOURCES)
            if retrieved:
                data_sources_used.append("chroma")
            if "article" in retrieved_entity_types:
                data_sources_used.append("articles")
            if "cfp" in retrieved_entity_types:
                data_sources_used.append("cfp_events")
            metadata_only_match = bool(quality_candidates) and all(
                not ((candidate.get("metadata", {}) or {}).get("supporting_evidence"))
                for candidate in quality_candidates
            )
            warning = (
                "Các gợi ý hiện dựa chủ yếu trên metadata venue nội bộ; bài báo hoặc policy chỉ được dùng khi có sẵn làm evidence bổ sung."
                if metadata_only_match
                else None
            )
            if broad_only_top_matches:
                warning = (
                    (warning + " " if warning else "")
                    + "Top matches currently rely on broad venue subjects more than exact topic phrases, so confidence is kept low."
                )
            request.retrieval_diagnostics = {
                **diagnostics,
                "debug": {
                    "extracted_title": local_diagnostics.get("extracted_title"),
                    "extracted_keywords": local_diagnostics.get("extracted_keywords"),
                    "detected_subjects": local_diagnostics.get("detected_subjects"),
                    "expanded_subjects": local_diagnostics.get("expanded_subjects"),
                    "candidate_count_before_filter": len(combined_candidates),
                    "candidate_count_after_filter": len(finalized),
                    "data_sources_used": data_sources_used,
                },
                **final_diagnostics,
                "match_status": match_status,
                "insufficient_corpus": match_status == "insufficient_corpus",
                "missing_manuscript_info": match_status == "missing_manuscript_info",
                "detected_domain": detected_domain,
                "topic_profile": topic_profile.to_dict(),
                "confidence": confidence,
                "warning": warning,
                "data_sources_used": data_sources_used,
                "metadata_only_match": metadata_only_match,
                "local_venue_count": local_diagnostics.get("local_venue_count", 0),
                "explanation": (
                    "No local venue candidate remained after compatibility filtering."
                    if match_status == "insufficient_corpus"
                    else None
                ),
                "retrieved_count_before_filters": len(combined_candidates),
                "candidate_count_before_filter": len(combined_candidates),
                "candidate_count_after_filter": len(finalized),
                "candidate_count": min(len(quality_candidates), top_k),
                "replaced_candidate_count": replaced_candidate_count,
                "no_candidates": len(ranked) == 0,
                "quality_filtered_candidates": len(quality_candidates),
                "optional_retriever_error": retriever_error,
                "embedding_model": next(
                    (candidate.get("metadata", {}).get("embedding_model") for candidate in ranked if candidate.get("metadata")),
                    None,
                ),
            }
            logger.info(
                "Match request %s completed status=%s candidates=%d retrieved=%d",
                request.id,
                request.status,
                min(len(ranked), top_k),
                len(combined_candidates),
            )
            db.add(request)
            db.commit()
            db.refresh(request)
            return request
        except Exception as exc:
            db.rollback()
            failed_request = db.query(MatchRequest).filter(MatchRequest.id == request_id, MatchRequest.user_id == current_user.id).first()
            if failed_request is None:
                raise
            failed_request.status = MatchRequestStatus.FAILED
            failed_request.executed_at = datetime.now(timezone.utc)
            failed_request.retrieval_diagnostics = {
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            }
            logger.exception("Match request %s failed", request_id)
            db.add(failed_request)
            db.commit()
            db.refresh(failed_request)
            return failed_request

    def get_result(self, db: Session, *, current_user: User, request_id: str) -> dict[str, Any]:
        request = db.query(MatchRequest).filter(MatchRequest.id == request_id, MatchRequest.user_id == current_user.id).first()
        if request is None:
            raise HTTPException(status_code=404, detail="Match request not found.")
        manuscript = db.query(Manuscript).filter(Manuscript.id == request.manuscript_id).first()
        assessment = (
            db.query(ManuscriptAssessment)
            .filter(ManuscriptAssessment.manuscript_id == request.manuscript_id)
            .first()
        )
        candidates = (
            db.query(MatchCandidate)
            .filter(MatchCandidate.match_request_id == request.id)
            .order_by(MatchCandidate.rank.asc())
            .all()
        )
        return {
            "request": request,
            "manuscript": manuscript,
            "assessment": assessment,
            "candidates": candidates,
        }

    def _is_journal_only(self, request: MatchRequest) -> bool:
        return str(request.desired_venue_type or "journal").lower() == "journal"

    def _venue_sources(self, db: Session, venue_id: str | None) -> list[str]:
        if not venue_id:
            return []
        rows = (
            db.query(EntityFingerprint.source_name)
            .filter(EntityFingerprint.entity_type == "venue", EntityFingerprint.entity_id == venue_id)
            .all()
        )
        return sorted({row[0] for row in rows if row[0]})

    def _source_trust_tier(self, source_name: str | None) -> str:
        if not source_name:
            return "missing"
        return self.SOURCE_TRUST_TIERS.get(source_name.lower(), "unverified")

    def _venue_source_details(self, db: Session, venue_id: str | None) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for source_name in self._venue_sources(db, venue_id):
            source = db.query(CrawlSource).filter(CrawlSource.slug == source_name).first()
            registry_config = None
            try:
                registry_config = source_registry.get(source_name)
            except Exception:
                registry_config = None
            snapshots = []
            if source is not None:
                try:
                    snapshots = (
                        db.query(RawSourceSnapshot)
                        .filter(RawSourceSnapshot.source_id == source.id, RawSourceSnapshot.content_hash.isnot(None))
                        .order_by(RawSourceSnapshot.fetched_at.desc().nullslast())
                        .limit(3)
                        .all()
                    )
                except SQLAlchemyError as exc:
                    logger.warning("Venue source snapshot lookup skipped for %s: %s", source_name, exc)
                    db.rollback()
            details.append(
                {
                    "source_name": source_name,
                    "source_type": registry_config.source_type if registry_config else source.source_type if source else None,
                    "crawl_source_type": source.source_type if source else None,
                    "access_mode": registry_config.access_mode if registry_config else None,
                    "trust_tier": self._source_trust_tier(source_name),
                    "official_source_reference": registry_config.base_url if registry_config else source.base_url if source else None,
                    "snapshot_hashes": [snapshot.content_hash for snapshot in snapshots if snapshot.content_hash],
                    "snapshot_urls": [snapshot.request_url for snapshot in snapshots if snapshot.request_url],
                }
            )
        return details

    def _production_eligibility(self, *, venue: Venue, source_details: list[dict[str, Any]]) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        title = (venue.title or "").strip()
        canonical_title = (venue.canonical_title or "").strip()
        if not self._valid_venue_title(title) or (canonical_title and not self._valid_venue_title(canonical_title)):
            reasons.append("invalid_venue_title")
        if not getattr(venue, "active", True):
            reasons.append("inactive_venue")
        if str(venue.venue_type.value).lower() not in {"journal", "conference"}:
            reasons.append("unsupported_venue_type")
        if not [subject for subject in venue.subjects if (subject.label or "").strip()]:
            reasons.append("missing_subject_metadata")
        source_keys = {str(source.get("source_name") or "").lower() for source in source_details}
        blocked_sources = sorted(source_keys & self.INTERNAL_SOURCE_SLUGS)
        if blocked_sources:
            reasons.append("internal_source:" + ",".join(blocked_sources))
        publisher = (venue.publisher or "").strip().lower()
        if publisher in self.INTERNAL_PUBLISHERS:
            reasons.append("synthetic_publisher")
        title_key = title.lower()
        if title_key in self.INTERNAL_TITLE_MARKERS:
            reasons.append("synthetic_title")
        return not reasons, reasons

    def _valid_venue_title(self, title: str) -> bool:
        if len(title) < 6 or len(title) > 500:
            return False
        if title.startswith("@"):
            return False
        if not re.search(r"[A-Za-z]", title):
            return False
        compact = re.sub(r"[^A-Za-z0-9]", "", title)
        if len(compact) < 4:
            return False
        alpha_count = len(re.findall(r"[A-Za-z]", title))
        if alpha_count / max(len(title), 1) < 0.35:
            return False
        return True

    def _attach_metric_provenance(self, metadata: dict[str, Any], source_details: list[dict[str, Any]]) -> dict[str, Any]:
        verified: dict[str, Any] = {}
        provenance: dict[str, str] = {}
        trusted_sources = [
            str(source.get("source_name"))
            for source in source_details
            if source.get("trust_tier") in self.PRODUCTION_TRUST_TIERS and source.get("source_name")
        ]
        if trusted_sources:
            source_label = ", ".join(sorted(set(trusted_sources)))
            for field in self.METRIC_FIELDS:
                if metadata.get(field) is not None:
                    verified[field] = metadata[field]
                    provenance[field] = source_label
        metadata["verified_metrics"] = verified
        metadata["metric_provenance"] = provenance
        metadata["unverified_metrics"] = sorted(field for field in self.METRIC_FIELDS if metadata.get(field) is not None and field not in verified)
        metadata["provenance_sources"] = sorted(set(trusted_sources))
        return metadata

    def _load_venue(self, db: Session, venue_id: str | None) -> Venue | None:
        if not venue_id:
            return None
        return (
            db.query(Venue)
            .options(selectinload(Venue.subjects), selectinload(Venue.metrics), selectinload(Venue.policies))
            .filter(Venue.id == venue_id)
            .first()
        )

    def _candidate_from_venue(
        self,
        db: Session,
        *,
        venue: Venue,
        base_candidate: dict[str, Any] | None = None,
        supporting_evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        document, metadata = self._build_local_venue_snapshot(venue)
        supporting_evidence = supporting_evidence or []
        source_details = self._venue_source_details(db, venue.id)
        production_eligible, eligibility_reasons = self._production_eligibility(venue=venue, source_details=source_details)
        metadata = self._attach_metric_provenance(metadata, source_details)
        metadata["primary_label"] = venue.title
        metadata["warning_flags"] = self._detect_warning_flags(venue)
        metadata["production_eligible"] = production_eligible
        metadata["production_eligibility_reasons"] = eligibility_reasons
        metadata["source_details"] = source_details
        metadata["trust_tiers"] = sorted({str(source.get("trust_tier")) for source in source_details if source.get("trust_tier")})
        metadata["source_types"] = sorted({str(source.get("source_type")) for source in source_details if source.get("source_type")})
        metadata["supporting_evidence"] = supporting_evidence[:3]
        metadata["metadata_only_match"] = not bool(supporting_evidence)
        base_metadata = (base_candidate or {}).get("metadata", {})
        for key in (
            "local_match_stage",
            "local_exact_score",
            "local_fuzzy_score",
            "local_semantic_score",
            "local_scope_score",
            "local_broad_score",
            "broad_subject_only",
        ):
            if key in base_metadata:
                metadata[key] = base_metadata[key]
        evidence_text = " ".join(str(item.get("excerpt") or item.get("title") or "") for item in supporting_evidence[:3])
        retrieval_score = float((base_candidate or {}).get("retrieval_score", 0.0))
        if supporting_evidence:
            retrieval_score = max(retrieval_score, max(float(item.get("retrieval_score") or 0.0) for item in supporting_evidence) * 0.95)
        return {
            "record_id": f"venue:{venue.id}",
            "collection": "venue_profiles",
            "retrieval_score": round(min(retrieval_score, 1.0), 4),
            "document": " ".join(part for part in [document, evidence_text] if part),
            "metadata": metadata,
        }

    def _supporting_evidence_item(self, candidate: dict[str, Any]) -> dict[str, Any]:
        metadata = candidate.get("metadata", {})
        entity_type = str(metadata.get("entity_type") or candidate.get("collection") or "evidence")
        return {
            "entity_type": entity_type,
            "title": metadata.get("title") or candidate.get("record_id"),
            "article_id": metadata.get("article_id"),
            "cfp_event_id": metadata.get("cfp_event_id"),
            "doi": metadata.get("doi"),
            "url": metadata.get("url") or metadata.get("source_url"),
            "publication_year": metadata.get("publication_year"),
            "deadline": metadata.get("full_paper_deadline") or metadata.get("abstract_deadline"),
            "retrieval_score": round(float(candidate.get("retrieval_score") or 0.0), 4),
            "excerpt": str(candidate.get("document") or "")[:240],
        }

    def _finalize_primary_candidates(
        self,
        db: Session,
        *,
        request: MatchRequest,
        manuscript_text: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        desired_type = str(request.desired_venue_type or "journal").lower()
        journal_only = self._is_journal_only(request)
        primary_by_venue: dict[str, dict[str, Any]] = {}
        evidence_by_venue: dict[str, list[dict[str, Any]]] = {}
        rejected: list[dict[str, Any]] = []

        for candidate in candidates:
            metadata = candidate.get("metadata", {})
            entity_type = str(metadata.get("entity_type") or "").lower()
            venue_type = str(metadata.get("venue_type") or "").lower()
            venue_id = metadata.get("venue_id")

            if entity_type == "venue":
                if venue_type != desired_type:
                    rejected.append({"record_id": candidate.get("record_id"), "reasons": [f"final_{desired_type}_venue_type_mismatch"]})
                    continue
                if not venue_id:
                    rejected.append({"record_id": candidate.get("record_id"), "reasons": ["final_missing_venue_id"]})
                    continue
                primary_by_venue[venue_id] = candidate
                continue

            if journal_only and entity_type == "article" and venue_id and venue_type == "journal":
                evidence_by_venue.setdefault(venue_id, []).append(self._supporting_evidence_item(candidate))
                continue

            if journal_only and entity_type == "cfp" and venue_id and venue_type == "journal":
                evidence_by_venue.setdefault(venue_id, []).append(self._supporting_evidence_item(candidate))
                rejected.append({"record_id": candidate.get("record_id"), "reasons": ["final_cfp_demoted_to_evidence"]})
                continue

            rejected.append({"record_id": candidate.get("record_id"), "reasons": [f"final_{desired_type}_primary_entity_type_mismatch"]})

        finalized: list[dict[str, Any]] = []
        candidate_venue_ids = sorted(
            set(primary_by_venue) | set(evidence_by_venue),
            key=lambda venue_id: (
                -max(
                    float((primary_by_venue.get(venue_id) or {}).get("retrieval_score") or 0.0),
                    max((float(item.get("retrieval_score") or 0.0) for item in evidence_by_venue.get(venue_id, [])), default=0.0),
                ),
                venue_id,
            ),
        )
        active_domains = match_reranker.active_domains(manuscript_text)
        detected_domain = match_reranker.inferred_domain_labels(manuscript_text)
        for venue_id in candidate_venue_ids:
            venue = self._load_venue(db, venue_id)
            if venue is None:
                rejected.append({"record_id": f"venue:{venue_id}", "reasons": ["final_venue_not_found"]})
                continue
            if str(venue.venue_type.value).lower() != desired_type:
                rejected.append({"record_id": f"venue:{venue_id}", "reasons": [f"final_loaded_{desired_type}_venue_type_mismatch"]})
                continue
            finalized_candidate = self._candidate_from_venue(
                db,
                venue=venue,
                base_candidate=primary_by_venue.get(venue_id),
                supporting_evidence=sorted(
                    evidence_by_venue.get(venue_id, []),
                    key=lambda item: float(item.get("retrieval_score") or 0.0),
                    reverse=True,
                ),
            )
            metadata = finalized_candidate.get("metadata", {})
            subject_mismatch = self._subject_compatibility_check(manuscript_text, metadata)
            if subject_mismatch:
                rejected.append({
                    "record_id": finalized_candidate.get("record_id"),
                    "reasons": ["subject_area_mismatch", *subject_mismatch],
                })
                continue
            if not metadata.get("production_eligible"):
                rejected.append({
                    "record_id": finalized_candidate.get("record_id"),
                    "reasons": ["not_production_eligible", *(metadata.get("production_eligibility_reasons") or [])],
                })
                continue
            hard_mismatch_reasons = match_reranker.hard_domain_mismatch(manuscript_text, finalized_candidate)
            if hard_mismatch_reasons:
                rejected.append({
                    "record_id": finalized_candidate.get("record_id"),
                    "reasons": ["hard_domain_mismatch", *hard_mismatch_reasons],
                })
                continue
            domain_fit_score, mismatch_reasons = match_reranker._domain_fit(manuscript_text, finalized_candidate)
            if mismatch_reasons:
                metadata["domain_fit_warnings"] = mismatch_reasons
            metadata["domain_fit_score"] = round(domain_fit_score, 4)
            finalized.append(finalized_candidate)

        finalized.sort(
            key=lambda item: (
                -float(item.get("retrieval_score") or 0.0),
                str(item.get("metadata", {}).get("primary_label") or item.get("record_id") or ""),
            )
        )
        return finalized, {
            "finalization": {
                "mode": "journal_only" if journal_only else f"{desired_type}_only",
                "active_domains": active_domains,
                "detected_domain": detected_domain,
                "primary_candidate_count": len(finalized),
                "supporting_evidence_count": sum(len(items) for items in evidence_by_venue.values()),
                "rejected": rejected,
            }
        }


journal_match_service = JournalMatchService()


def build_legacy_journal_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in result.get("candidates", []):
        metadata = (candidate.evidence_payload or {}).get("metadata", {}) if hasattr(candidate, "evidence_payload") else {}
        explanation = candidate.explanation_payload or {} if hasattr(candidate, "explanation_payload") else {}
        verified_metrics = metadata.get("verified_metrics") if isinstance(metadata.get("verified_metrics"), dict) else {}
        metric_provenance = metadata.get("metric_provenance") if isinstance(metadata.get("metric_provenance"), dict) else {}
        unverified_metrics = metadata.get("unverified_metrics")
        if not isinstance(unverified_metrics, list):
            unverified_metrics = sorted(
                field
                for field in JournalMatchService.METRIC_FIELDS
                if metadata.get(field) is not None and field not in verified_metrics
            )
        supporting_evidence = metadata.get("supporting_evidence") or []
        score_breakdown = {
            "retrieval_score": round(float(getattr(candidate, "retrieval_score", 0.0)), 4),
            "scope_overlap_score": round(float(getattr(candidate, "scope_overlap_score", 0.0)), 4),
            "quality_fit_score": round(float(getattr(candidate, "quality_fit_score", 0.0)), 4),
            "policy_fit_score": round(float(getattr(candidate, "policy_fit_score", 0.0)), 4),
            "freshness_score": round(float(getattr(candidate, "freshness_score", 0.0)), 4),
            "manuscript_readiness_score": round(float(getattr(candidate, "manuscript_readiness_score", 0.0)), 4),
            "penalty_score": round(float(getattr(candidate, "penalty_score", 0.0)), 4),
            "final_score": round(float(getattr(candidate, "final_score", 0.0)), 4),
        }
        warning_flags = metadata.get("warning_flags") or []
        if metadata.get("broad_subject_only") and "broad_subject_only" not in warning_flags:
            warning_flags = [*warning_flags, "broad_subject_only"]
        subject_labels = metadata.get("subject_labels") or metadata.get("topic_tags") or ""
        scope_fit = _build_scope_fit(metadata, subject_labels, warning_flags)
        links, primary_url, link_warning = JournalMatchService.build_trusted_venue_links(metadata)
        rows.append(
            {
                "candidate_id": getattr(candidate, "id", None),
                "id": metadata.get("venue_id") or getattr(candidate, "id", None),
                "name": metadata.get("primary_label") or metadata.get("title") or metadata.get("venue_id") or candidate.entity_type,
                "journal": metadata.get("primary_label") or metadata.get("title") or metadata.get("venue_id") or candidate.entity_type,
                "venue_id": metadata.get("venue_id"),
                "venue_type": metadata.get("venue_type"),
                "entity_type": "venue",
                "production_eligible": bool(metadata.get("production_eligible", True)),
                "score": round(float(getattr(candidate, "final_score", 0.0)), 4),
                "score_calibrated": False,
                "reason": explanation.get("summary") or "Gợi ý này dựa trên dữ liệu học thuật đã index.",
                "url": primary_url or metadata.get("homepage_url") or metadata.get("source_url") or metadata.get("url"),
                "impact_factor": verified_metrics.get("impact_factor"),
                "publisher": metadata.get("publisher"),
                "open_access": bool(verified_metrics.get("is_open_access", False)),
                "issn": JournalMatchService._normalize_issn(metadata.get("issn")),
                "eissn": JournalMatchService._normalize_issn(metadata.get("eissn")),
                "h_index": verified_metrics.get("h_index"),
                "review_time_weeks": verified_metrics.get("avg_review_weeks"),
                "acceptance_rate": verified_metrics.get("acceptance_rate"),
                "citescore": verified_metrics.get("citescore"),
                "sjr_quartile": verified_metrics.get("sjr_quartile"),
                "jcr_quartile": verified_metrics.get("jcr_quartile"),
                "indexed_scopus": verified_metrics.get("indexed_scopus"),
                "indexed_wos": verified_metrics.get("indexed_wos"),
                "domains": [item.strip() for item in str(subject_labels).split(",") if item.strip()],
                "detected_domains": [],
                "deadline": None,
                "supporting_evidence": supporting_evidence,
                "metric_provenance": metric_provenance,
                "unverified_metrics": unverified_metrics,
                "source_details": metadata.get("source_details") or [],
                "trust_tiers": metadata.get("trust_tiers") or [],
                "score_breakdown": score_breakdown,
                "warning_flags": warning_flags,
                "scope_fit": scope_fit,
                "evidence_count": len(supporting_evidence),
                "links": links,
                "link_warning": link_warning,
            }
        )
    return rows


def _build_scope_fit(metadata: dict[str, Any], subject_labels: str | list[str], warning_flags: list[str]) -> str | None:
    parts: list[str] = []
    if isinstance(subject_labels, str) and subject_labels.strip():
        parts.append(f"Subjects: {subject_labels}")
    elif isinstance(subject_labels, list) and subject_labels:
        parts.append(f"Subjects: {', '.join(subject_labels)}")
    publisher = metadata.get("publisher")
    if publisher:
        parts.append(f"Publisher: {publisher}")
    quartile = (metadata.get("verified_metrics") or {}).get("sjr_quartile") or (metadata.get("verified_metrics") or {}).get("jcr_quartile")
    if quartile:
        parts.append(f"Quartile: {quartile}")
    if warning_flags:
        parts.append(f"Warnings: {', '.join(warning_flags)}")
    return "; ".join(parts) if parts else None


def build_legacy_journal_payload(result: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    request = result.get("request")
    candidates = result.get("candidates", [])
    rows = build_legacy_journal_rows(result)
    diagnostics = getattr(request, "retrieval_diagnostics", None) or {}
    summary = format_journal_match_summary(
        status=getattr(request, "status", None),
        candidate_count=len(candidates),
        diagnostics=diagnostics,
    )
    return rows, summary


def build_chat_journal_match_payload(result: dict[str, Any]) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    request = result.get("request")
    diagnostics = getattr(request, "retrieval_diagnostics", None) or {}
    raw_rows = build_legacy_journal_rows(result)
    summary = format_journal_match_summary(
        status=getattr(request, "status", None),
        candidate_count=len(raw_rows),
        diagnostics=diagnostics,
    )
    candidate_ids = [
        row.get("candidate_id") or row.get("venue_id")
        for row in raw_rows
        if isinstance(row, dict) and (row.get("candidate_id") or row.get("venue_id"))
    ]
    matches: list[dict[str, Any]] = []
    for row in raw_rows:
        metrics = {
            "impact_factor": row.get("impact_factor"),
            "h_index": row.get("h_index"),
            "review_time_weeks": row.get("review_time_weeks"),
            "acceptance_rate": row.get("acceptance_rate"),
            "open_access": row.get("open_access"),
            "citescore": row.get("citescore"),
            "sjr_quartile": row.get("sjr_quartile"),
            "jcr_quartile": row.get("jcr_quartile"),
            "indexed_scopus": row.get("indexed_scopus"),
            "indexed_wos": row.get("indexed_wos"),
        }
        matches.append({
            "id": row.get("id") or row.get("venue_id"),
            "name": row.get("name") or row.get("journal", ""),
            "journal": row.get("journal", ""),
            "venue_id": row.get("venue_id"),
            "venue_type": row.get("venue_type"),
            "score": row.get("score"),
            "reason": row.get("reason"),
            "subject_fit": row.get("scope_fit"),
            "publisher": row.get("publisher"),
            "url": row.get("url"),
            "issn": row.get("issn"),
            "eissn": row.get("eissn"),
            "links": row.get("links") or [],
            "link_warning": row.get("link_warning"),
            "supporting_evidence": row.get("supporting_evidence"),
            "warning_flags": row.get("warning_flags"),
            "metric_provenance": row.get("metric_provenance"),
            "unverified_metrics": row.get("unverified_metrics"),
            "metrics": metrics,
        })
    match_status = diagnostics.get("match_status") or ("matched" if matches else "insufficient_corpus")
    payload = {
        "type": "journal_match",
        "matches": matches,
        "request_id": request.id if request else None,
        "candidate_ids": candidate_ids,
        "status": match_status,
        "confidence": diagnostics.get("confidence"),
    }
    if diagnostics.get("warning"):
        payload["warning"] = diagnostics.get("warning")
    if settings.app_env != "production" or settings.debug:
        debug_payload = diagnostics.get("debug")
        if isinstance(debug_payload, dict):
            payload["debug"] = debug_payload
    return matches, summary, payload
