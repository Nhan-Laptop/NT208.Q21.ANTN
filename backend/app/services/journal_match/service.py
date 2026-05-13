from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

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

    @staticmethod
    def _enrich_query_for_computing(query_text: str) -> str:
        terms = set(re.findall(r"[a-z][a-z0-9\-]{2,}", query_text.lower()))
        if terms & JournalMatchService.COMPUTING_BOOST_TERMS:
            return query_text + "\n" + JournalMatchService.COMPUTING_BOOST_SUFFIX
        return query_text

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
            retrieved = manuscript_retriever.retrieve(query_text=query_text, top_k_each=max(5, min(top_k, 10)))
            if not request.include_cfps and not self._is_journal_only(request):
                retrieved = [candidate for candidate in retrieved if candidate.get("metadata", {}).get("entity_type") != "cfp"]
            filtered, diagnostics = match_filters.apply(request, retrieved)
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

            MIN_QUALITY_THRESHOLD = 0.25
            quality_candidates = [c for c in ranked[:top_k] if c["final_score"] >= MIN_QUALITY_THRESHOLD]
            if len(quality_candidates) < 2 and len(ranked) >= 2:
                quality_candidates = ranked[:min(2, len(ranked))]

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

            readiness = assessment.readiness_score if assessment else 0.5
            manuscript_has_content = readiness >= 0.35

            match_status = (
                "matched" if quality_candidates else
                ("missing_manuscript_info" if not manuscript_has_content else "insufficient_corpus")
            )
            request.retrieval_diagnostics = {
                **diagnostics,
                **final_diagnostics,
                "match_status": match_status,
                "insufficient_corpus": match_status == "insufficient_corpus",
                "missing_manuscript_info": match_status == "missing_manuscript_info",
                "detected_domain": detected_domain,
                "topic_profile": topic_profile.to_dict(),
                "explanation": (
                    "No production-eligible venue remained after subject/provenance/domain compatibility filters."
                    if match_status == "insufficient_corpus"
                    else None
                ),
                "retrieved_count_before_filters": len(retrieved),
                "candidate_count": min(len(quality_candidates), top_k),
                "replaced_candidate_count": replaced_candidate_count,
                "no_candidates": len(ranked) == 0,
                "quality_filtered_candidates": len(quality_candidates),
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
                len(retrieved),
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
        if not source_keys:
            reasons.append("missing_source_provenance")
        trusted_sources = [
            source
            for source in source_details
            if source.get("trust_tier") in self.PRODUCTION_TRUST_TIERS
        ]
        if source_keys and not trusted_sources:
            reasons.append("missing_trusted_source_provenance")
        source_types = {str(source.get("source_type") or source.get("crawl_source_type") or "").lower() for source in source_details}
        source_types.discard("")
        has_supported_source_type = bool(source_types & self.PRODUCTION_SOURCE_TYPES)
        has_known_trusted_source = bool(source_keys & set(self.SOURCE_TRUST_TIERS))
        if source_keys and not has_supported_source_type and not has_known_trusted_source:
            reasons.append("unsupported_source_type")
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
        document, metadata = academic_index_service.build_venue_document(venue)
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
            failed_domains = [
                domain
                for domain in active_domains
                if domain_fit_score < self.STRICT_DOMAIN_MIN_FIT.get(domain, 0.0)
            ]
            if failed_domains:
                rejected.append({
                    "record_id": finalized_candidate.get("record_id"),
                    "reasons": ["strict_domain_mismatch", *mismatch_reasons, *failed_domains],
                })
                continue
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
        subject_labels = metadata.get("subject_labels") or metadata.get("topic_tags") or ""
        scope_fit = _build_scope_fit(metadata, subject_labels, warning_flags)
        rows.append(
            {
                "candidate_id": getattr(candidate, "id", None),
                "journal": metadata.get("primary_label") or metadata.get("title") or metadata.get("venue_id") or candidate.entity_type,
                "venue_id": metadata.get("venue_id"),
                "venue_type": metadata.get("venue_type"),
                "entity_type": "venue",
                "production_eligible": bool(metadata.get("production_eligible", True)),
                "score": round(float(getattr(candidate, "final_score", 0.0)), 4),
                "score_calibrated": False,
                "reason": explanation.get("summary") or "Gợi ý này dựa trên dữ liệu học thuật đã index.",
                "url": metadata.get("homepage_url") or metadata.get("source_url") or metadata.get("url"),
                "impact_factor": verified_metrics.get("impact_factor"),
                "publisher": metadata.get("publisher"),
                "open_access": bool(verified_metrics.get("is_open_access", False)),
                "issn": None,
                "h_index": verified_metrics.get("h_index"),
                "review_time_weeks": verified_metrics.get("avg_review_weeks"),
                "acceptance_rate": verified_metrics.get("acceptance_rate"),
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
