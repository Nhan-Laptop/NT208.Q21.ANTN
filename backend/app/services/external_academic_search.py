from __future__ import annotations

import copy
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.article import Article
from app.models.article_author import ArticleAuthor
from app.services.academic_query_service import AcademicQueryResult, academic_query_service
from app.services.tools.citation import (
    CandidateWork,
    ReferenceMetadata,
    build_fallback_title_query,
    choose_best_match,
    compare_reference_to_candidate,
    normalize_author_name,
    normalize_doi,
    normalize_title,
    normalize_venue,
    parse_reference_metadata,
)
from app.services.tools.citation.sources.crossref import CROSSREF_WORKS_URL, normalize_crossref_work
from app.services.tools.citation.sources.openalex import OPENALEX_WORKS_URL, normalize_openalex_work
from app.services.tools.citation.sources.semantic_scholar import (
    SEMANTIC_SCHOLAR_SEARCH_URL,
    normalize_semantic_scholar_paper,
)
from app.services.tools.citation.sources.web_search import WebSearchSource
from app.services.tools.citation_checker import CitationCheckResult, citation_checker


logger = logging.getLogger(__name__)

_SOURCE_LABELS = {
    "internal": "Internal academic database",
    "crossref": "Crossref",
    "openalex": "OpenAlex",
    "pubmed": "PubMed",
    "semantic_scholar": "Semantic Scholar",
    "datacite": "DataCite",
    "publisher_meta": "Publisher metadata",
    "web_search": "Web search",
}
_DEGRADED_STATES = {"timeout", "http_error", "error", "rate_limited"}
_PAPER_HEADER_AFFILIATION_RE = re.compile(
    r"^(?:\d+\s*)?(?:department|school|faculty|college|program|laboratory|lab|center|centre|university|hospital|institute)\b",
    re.IGNORECASE,
)
_PAPER_HEADER_AUTHOR_RE = re.compile(
    r"[A-Z][A-Za-z'\-]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][A-Za-z'\-]+)+"
)
_ACADEMIC_CONTEXT_RE = re.compile(
    r"\b(doi|journal|conference|authors?|abstract|university|department|manuscript|paper|article)\b",
    re.IGNORECASE,
)
_PUBMED_HINT_RE = re.compile(
    r"\b("
    r"working\s+memory|memory|cognition|cognitive|psychology|psychological|"
    r"neuroscience|neural|brain|biomedical|medicine|medical|biology|health"
    r")\b",
    re.IGNORECASE,
)
_SEMANTIC_SCHOLAR_LOOKUP_FIELDS = (
    "paperId,url,title,authors,year,venue,externalIds,publicationTypes,publicationDate,abstract,fieldsOfStudy"
)
OPENALEX_AUTHORS_URL = "https://api.openalex.org/authors"
_PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_TITLE_GATE_THRESHOLD = 0.75
_TITLE_STRONG_GATE_THRESHOLD = 0.85
_POSSIBLE_MATCH_THRESHOLD = 0.60
_QUERY_TYPE_CITATION_ABSTRACT = "paper_lookup_from_citation_and_abstract"
_QUERY_TYPE_GENERIC = "generic_lookup"
_QUERY_TYPE_TITLE_KNOWN = "title_known_lookup"
_WEB_SEARCH_SOURCE = WebSearchSource()
_STRONG_TERMS_RE = re.compile(
    r"\b(?:"
    r"[A-Z][a-z]+(?:\.[a-z]+)*"  # ProperCased terms
    r"|[A-Z]{2,}(?:-[A-Z]+)*"  # Acronyms like EC, ECCE
    r"|[a-z]+\.[a-z]+(?:\.[a-z]+)*"  # Domain-like terms like Leurre.com
    r")\b",
)
_SEMICOLON_AUTHOR_RE = re.compile(
    r"^(?:[A-Z][A-Za-z'\-]+(?:,\s+[A-Z][A-Za-z'\-]+){0,2}(?:\s*[;]\s*|$)){2,}"
)
_COMMA_AUTHOR_RE = re.compile(
    r"^(?:[A-Z][A-Za-z'\-]+,\s+[A-Z][A-Za-z'\-]+(?:\s+[A-Z]\.?)?(?:\s*[,;]\s*|$)){2,}"
)
_VENUE_LINE_RE = re.compile(
    r"\b(?:"
    r"(?:19|20)\d{2}"  # year
    r"|conference|proceedings|workshop|symposium|journal|lecture|notes|springer|"
    r"ieee|acm|elsevier|inria|cnrs|university|institute|school|college|"
    r"ecce|icse|fse|ase|popl|pldi|oopsla|sigcomm|sigmod|"
    r"p[:ivxlcdm]+"  # pages like pp. 1-12
    r"|pp\.?\s*\d+"
    r")\b",
    re.IGNORECASE,
)
_PRESERVED_ENTITY_RE = re.compile(
    r"[A-Z][a-zA-Z]*\.(?:com|org|net|fr|uk|de|jp)"  # Leurre.com, etc.
    r"|[A-Z][a-z]+[\-\s][A-Z][a-z]+"  # Multi-word names
)


@dataclass(slots=True)
class ScholarlyLookupResult:
    status: str
    source_mode: str
    records: list[dict[str, Any]]
    best_record: dict[str, Any] | None
    query_terms: list[str]
    confidence: float
    confidence_label: str | None
    external_search_used: bool
    checked_sources: list[dict[str, Any]]
    source_diagnostics: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    internal_result: dict[str, Any] | None = None
    low_confidence_records: list[dict[str, Any]] = field(default_factory=list)
    source_health: str = "healthy"
    input_reference: dict[str, Any] | None = None
    rejected_candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ParsedScholarlyQuery:
    reference: ReferenceMetadata
    notes: list[str] = field(default_factory=list)
    query_hint: str | None = None
    query_type: str = "generic_lookup"
    search_queries: list[str] = field(default_factory=list)
    strong_terms: list[str] = field(default_factory=list)
    input_reference: dict[str, Any] | None = None


@dataclass(slots=True)
class AuthorPublicationLookupResult:
    status: str
    source_record: dict[str, Any] | None
    authors: list[dict[str, Any]]
    external_search_used: bool
    notes: list[str] = field(default_factory=list)
    checked_sources: list[dict[str, Any]] = field(default_factory=list)


class ExternalAcademicSearchService:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, ScholarlyLookupResult]] = {}

    def should_handle(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return False

        if academic_query_service.should_handle(normalized):
            return True
        if citation_checker.extract_dois(normalized):
            return True
        if citation_checker.extract_exact_identifiers(normalized):
            return True

        header = self._parse_paper_header(normalized)
        if header is not None:
            return True

        if len(normalized) < 40:
            return False

        parsed = parse_reference_metadata(normalized)
        if parsed.title and (parsed.authors or parsed.year is not None or parsed.venue):
            return True

        fallback_title = build_fallback_title_query(normalized, parsed)
        return bool(fallback_title and ("\n" in normalized or _ACADEMIC_CONTEXT_RE.search(normalized)))

    def lookup(self, db: Session, text: str) -> ScholarlyLookupResult:
        parsed_query = self._parse_query(text)
        query_hint = parsed_query.query_hint or text
        internal_lookup = academic_query_service.lookup(db, text, query_hint=query_hint)
        internal_checked = self._internal_checked_source(internal_lookup)
        checked_sources = [internal_checked]
        internal_result = {
            "count": len(internal_lookup.records),
            "best_score": internal_lookup.best_score,
            "confidence": internal_lookup.confidence,
        }

        if academic_query_service.has_sufficient_confidence(internal_lookup):
            records = [self._normalize_internal_record(record, internal_lookup.confidence) for record in internal_lookup.records]
            best_record = records[0] if records else None
            return ScholarlyLookupResult(
                status="internal_found",
                source_mode="internal_corpus",
                records=records,
                best_record=best_record,
                query_terms=internal_lookup.query_terms,
                confidence=round(internal_lookup.confidence, 3),
                confidence_label=self._confidence_label(internal_lookup.confidence),
                external_search_used=False,
                checked_sources=checked_sources,
                source_diagnostics={"internal": {"state": internal_checked["state"], "candidate_count": len(records), "detail": internal_checked["detail"]}},
                notes=list(parsed_query.notes),
                internal_result=internal_result,
            )

        cache_key = self._cache_key(text, parsed_query.reference)
        cached = self._get_cached(cache_key)
        if cached is not None:
            cached.checked_sources = [internal_checked, *[source for source in cached.checked_sources if source.get("name") != _SOURCE_LABELS["internal"]]]
            cached.internal_result = internal_result
            return cached

        if not settings.enable_external_academic_search:
            result = ScholarlyLookupResult(
                status="not_found",
                source_mode="external_scholarly",
                records=[],
                best_record=None,
                query_terms=internal_lookup.query_terms,
                confidence=0.0,
                confidence_label=None,
                external_search_used=False,
                checked_sources=[
                    *checked_sources,
                    self._checked_source("crossref", "disabled", detail="External academic fallback is disabled."),
                    self._checked_source("openalex", "disabled", detail="External academic fallback is disabled."),
                ],
                source_diagnostics={
                    "crossref": {"state": "disabled", "candidate_count": 0, "detail": "External academic fallback is disabled."},
                    "openalex": {"state": "disabled", "candidate_count": 0, "detail": "External academic fallback is disabled."},
                },
                notes=[*parsed_query.notes, "External academic search is disabled by configuration."],
                internal_result=internal_result,
            )
            self._set_cached(cache_key, result)
            return copy.deepcopy(result)

        external_result = self._lookup_external(text, parsed_query)
        external_result.checked_sources = [internal_checked, *external_result.checked_sources]
        external_result.internal_result = internal_result
        if not external_result.query_terms:
            external_result.query_terms = internal_lookup.query_terms
        self._set_cached(cache_key, external_result)
        return copy.deepcopy(external_result)

    def lookup_author_publications(
        self,
        db: Session,
        *,
        source_record: dict[str, Any] | None,
        authors: list[dict[str, Any]],
        source_doi: str | None = None,
        source_title: str | None = None,
        max_authors: int = 3,
        publications_per_author: int = 3,
    ) -> AuthorPublicationLookupResult:
        normalized_doi = normalize_doi(source_doi or "") if source_doi else None
        normalized_title = normalize_title(source_title or (source_record or {}).get("title") or "")
        selected_authors = [author for author in authors if str(author.get("name") or "").strip()]
        notes: list[str] = []
        if len(selected_authors) > max_authors:
            notes.append(
                f"The source paper has {len(selected_authors)} authors; showing other publications for the first {max_authors} authors only."
            )
        selected_authors = selected_authors[:max_authors]

        author_entries: list[dict[str, Any]] = []
        overall_checked_sources: list[dict[str, Any]] = []
        any_publications = False
        external_search_used = False
        degraded = False

        for author in selected_authors:
            entry_notes = list(author.get("notes") or [])
            author_name = str(author.get("name") or "").strip()
            author_orcid = self._normalize_orcid(author.get("orcid"))
            openalex_id = self._openalex_author_key(author.get("openalex_id") or (author.get("external_ids") or {}).get("openalex"))
            resolved_openalex_id = openalex_id
            identity_confidence = float(author.get("confidence") or 0.0)
            checked_sources: list[dict[str, Any]] = []

            internal_records, internal_checked = self._search_internal_author_publications(
                db,
                author_name=author_name,
                author_orcid=author_orcid,
                exclude_doi=normalized_doi,
                exclude_title=normalized_title,
                limit=max(publications_per_author + 2, 5),
            )
            checked_sources.append(internal_checked)

            publication_records = list(internal_records)
            if internal_records:
                any_publications = True

            if settings.enable_external_academic_search:
                external_search_used = external_search_used or settings.openalex_enabled or settings.crossref_enabled or settings.web_search_provider != "disabled"
                if settings.openalex_enabled:
                    resolved_openalex_id, author_checked, resolve_notes, resolved_confidence = self._resolve_openalex_author(
                        name=author_name,
                        orcid=author_orcid,
                        openalex_id=openalex_id,
                    )
                    checked_sources.append(author_checked)
                    entry_notes.extend(resolve_notes)
                    if resolved_confidence is not None:
                        identity_confidence = max(identity_confidence, resolved_confidence)
                else:
                    checked_sources.append(self._checked_source("openalex", "disabled", detail="OpenAlex author lookup is disabled."))
                    resolved_openalex_id = openalex_id

                if resolved_openalex_id and settings.openalex_enabled:
                    openalex_hits, openalex_diag = self._search_openalex_author_works(
                        resolved_openalex_id,
                        limit=max(publications_per_author + 3, 6),
                    )
                    checked_sources.append(self._diagnostic_to_checked_source("openalex", openalex_diag))
                    if openalex_diag.get("state") in _DEGRADED_STATES:
                        degraded = True
                    publication_records.extend(
                        self._dedupe_publication_records(
                            [
                                self._record_from_candidate(
                                    candidate,
                                    confidence=max(identity_confidence, 0.78),
                                    match_status="author_publication_match",
                                    evidence={"final_score": max(identity_confidence, 0.78)},
                                )
                                for candidate in openalex_hits
                            ],
                            exclude_doi=normalized_doi,
                            exclude_title=normalized_title,
                        )
                    )
                elif settings.openalex_enabled:
                    entry_notes.append("OpenAlex could not resolve a stable author profile for this name.")

                if settings.crossref_enabled and len(publication_records) < publications_per_author:
                    crossref_hits, crossref_diag = self._search_crossref_author_works(
                        author_name,
                        limit=max(publications_per_author + 4, 6),
                    )
                    checked_sources.append(self._diagnostic_to_checked_source("crossref", crossref_diag))
                    if crossref_diag.get("state") in _DEGRADED_STATES:
                        degraded = True
                    filtered_crossref = [
                        candidate
                        for candidate in crossref_hits
                        if any(self._author_name_matches(candidate_author, author_name) for candidate_author in candidate.authors or [])
                    ]
                    publication_records.extend(
                        self._dedupe_publication_records(
                            [
                                self._record_from_candidate(
                                    candidate,
                                    confidence=max(identity_confidence, 0.64),
                                    match_status="author_publication_name_match",
                                    evidence={"final_score": max(identity_confidence, 0.64)},
                                )
                                for candidate in filtered_crossref
                            ],
                            exclude_doi=normalized_doi,
                            exclude_title=normalized_title,
                        )
                    )
                elif settings.enable_external_academic_search:
                    checked_sources.append(self._checked_source("crossref", "disabled", detail="Crossref author lookup is disabled."))

                if len(publication_records) < publications_per_author:
                    web_records, web_diag, web_notes = self._search_web_author_publications(
                        author_name,
                        source_title=source_title,
                        exclude_doi=normalized_doi,
                        exclude_title=normalized_title,
                        limit=max(publications_per_author + 3, 6),
                    )
                    checked_sources.append(self._diagnostic_to_checked_source("web_search", web_diag))
                    entry_notes.extend(web_notes)
                    if web_diag.get("state") in _DEGRADED_STATES:
                        degraded = True
                    publication_records.extend(
                        self._dedupe_publication_records(
                            web_records,
                            exclude_doi=normalized_doi,
                            exclude_title=normalized_title,
                        )
                    )
                else:
                    checked_sources.append(self._checked_source("web_search", "skipped", detail="Existing sources already produced enough author publications."))
            else:
                checked_sources.extend(
                    [
                        self._checked_source("openalex", "disabled", detail="External academic fallback is disabled."),
                        self._checked_source("crossref", "disabled", detail="External academic fallback is disabled."),
                        self._checked_source("web_search", "disabled", detail="External academic fallback is disabled."),
                    ]
                )

            publication_records = self._dedupe_publication_records(
                publication_records,
                exclude_doi=normalized_doi,
                exclude_title=normalized_title,
            )
            publication_records.sort(
                key=lambda record: (
                    int(record.get("year") or 0),
                    float(record.get("confidence") or 0.0),
                ),
                reverse=True,
            )
            publication_records = publication_records[:publications_per_author]

            if publication_records:
                any_publications = True

            if not author_orcid and not resolved_openalex_id:
                entry_notes.append(
                    "Author identity was matched by name only; results may be incomplete or mixed with another researcher with a similar name."
                )

            author_entry = {
                "name": author_name,
                "orcid": author_orcid,
                "external_ids": {
                    "openalex": resolved_openalex_id,
                },
                "confidence": round(identity_confidence, 3) if identity_confidence else None,
                "identity_status": (
                    "resolved"
                    if author_orcid or resolved_openalex_id
                    else "name_only"
                ),
                "checked_sources": checked_sources,
                "publications": publication_records,
                "publication_count": len(publication_records),
                "notes": self._dedupe_strings(entry_notes),
            }
            author_entries.append(author_entry)
            overall_checked_sources = self._merge_checked_sources(overall_checked_sources, checked_sources)

        status = "matched" if any_publications else ("source_degraded" if degraded else "not_found")
        if not author_entries and source_record is not None:
            notes.append("No author metadata was available for the resolved source paper.")
        if external_search_used:
            notes.append("External scholarly sources were checked to expand author-publication coverage beyond the resolved source paper.")

        return AuthorPublicationLookupResult(
            status=status,
            source_record=source_record,
            authors=author_entries,
            external_search_used=external_search_used,
            notes=self._dedupe_strings(notes),
            checked_sources=overall_checked_sources,
        )

    def _lookup_external(self, text: str, parsed_query: ParsedScholarlyQuery) -> ScholarlyLookupResult:
        exact_result = self._lookup_exact_identifier(text)
        if exact_result is not None:
            exact_result.notes = [*parsed_query.notes, *exact_result.notes]
            return exact_result

        ref = parsed_query.reference
        source_diagnostics: dict[str, Any] = {}
        is_structured = parsed_query.query_type == _QUERY_TYPE_CITATION_ABSTRACT
        has_trusted_title = parsed_query.query_type == _QUERY_TYPE_TITLE_KNOWN or bool(ref.title and ref.confidence >= 0.75)

        crossref_hits, source_diagnostics["crossref"] = self._search_crossref(ref, parsed_query=parsed_query)
        openalex_hits, source_diagnostics["openalex"] = self._search_openalex(ref, parsed_query=parsed_query)
        candidates = self._merge_candidates(crossref_hits, openalex_hits)
        preliminary = choose_best_match(ref, candidates) if candidates else None

        if settings.pubmed_enabled and self._should_query_pubmed(ref, preliminary):
            preferred_doi = ref.doi or (preliminary.best_candidate.doi if preliminary and preliminary.best_candidate else None)
            pubmed_hits, source_diagnostics["pubmed"] = self._search_pubmed(ref, preferred_doi=preferred_doi)
            candidates = self._merge_candidates(candidates, pubmed_hits)
        elif settings.pubmed_enabled:
            source_diagnostics["pubmed"] = {
                "state": "skipped",
                "candidate_count": 0,
                "detail": "PubMed fallback was not needed for this query.",
            }
        else:
            source_diagnostics["pubmed"] = {"state": "disabled", "candidate_count": 0, "detail": "PubMed fallback is disabled."}

        if is_structured and parsed_query.search_queries and (not candidates or preliminary is None or preliminary.confidence < _POSSIBLE_MATCH_THRESHOLD):
            for sq in parsed_query.search_queries[:3]:
                sq_ref = ReferenceMetadata(raw=sq, title=sq, authors=ref.authors, year=ref.year, confidence=0.50)
                extra_crossref, _ = self._search_crossref(sq_ref, parsed_query=parsed_query)
                extra_openalex, _ = self._search_openalex(sq_ref, parsed_query=parsed_query)
                extra_candidates = self._merge_candidates(extra_crossref, extra_openalex)
                candidates = self._merge_candidates(candidates, extra_candidates)
                if len(candidates) >= 10:
                    break

        post_primary = choose_best_match(ref, candidates) if candidates else None
        degraded_primary = self._diagnostics_include_degradation(source_diagnostics, ("crossref", "openalex", "pubmed"))
        accepted_primary = post_primary is not None and self._candidate_classification(post_primary.confidence, post_primary.evidence, has_trusted_title=has_trusted_title) == "external_found"
        need_semantic = (
            settings.semantic_scholar_enabled
            and (
                not accepted_primary
                or not candidates
                or post_primary is None
                or post_primary.confidence < max(settings.external_academic_min_confidence, _TITLE_STRONG_GATE_THRESHOLD)
                or degraded_primary
            )
        )
        if need_semantic:
            semantic_hits, source_diagnostics["semantic_scholar"] = self._search_semantic_scholar(ref, parsed_query=parsed_query)
            candidates = self._merge_candidates(candidates, semantic_hits)
        elif settings.semantic_scholar_enabled:
            source_diagnostics["semantic_scholar"] = {"state": "skipped", "candidate_count": 0, "detail": "Primary scholarly sources were sufficient."}
        else:
            source_diagnostics["semantic_scholar"] = {"state": "disabled", "candidate_count": 0, "detail": "Semantic Scholar fallback is disabled."}

        checked_sources = [
            self._diagnostic_to_checked_source("crossref", source_diagnostics["crossref"]),
            self._diagnostic_to_checked_source("openalex", source_diagnostics["openalex"]),
            self._diagnostic_to_checked_source("pubmed", source_diagnostics["pubmed"]),
            self._diagnostic_to_checked_source("semantic_scholar", source_diagnostics["semantic_scholar"]),
        ]

        if not candidates:
            status = "source_degraded" if self._diagnostics_include_degradation(source_diagnostics) else "not_found"
            notes = list(parsed_query.notes)
            if status == "source_degraded":
                notes.append("One or more external scholarly sources were unavailable during lookup.")
            source_health = "degraded" if self._diagnostics_include_degradation(source_diagnostics) else "healthy"
            return ScholarlyLookupResult(
                status=status,
                source_mode="external_scholarly",
                records=[],
                best_record=None,
                query_terms=self._query_terms_from_reference(ref),
                confidence=0.0,
                confidence_label=None,
                external_search_used=True,
                checked_sources=checked_sources,
                source_diagnostics=source_diagnostics,
                notes=notes,
                low_confidence_records=[],
                source_health=source_health,
                input_reference=parsed_query.input_reference,
            )

        ranked = self._rank_candidates(ref, candidates)
        overall_degraded = self._diagnostics_include_degradation(source_diagnostics)
        source_health = "degraded" if overall_degraded else "healthy"

        if is_structured and parsed_query.input_reference:
            gated = self._relevance_gate(ranked, parsed_query)
            ranked = gated["surviving"]
            rejected = gated["rejected"]
        else:
            rejected = []

        best_record = None
        records: list[dict[str, Any]] = []
        low_confidence_records: list[dict[str, Any]] = []
        strong_ranked: list[tuple[CandidateWork, dict[str, Any]]] = []
        possible_ranked: list[tuple[CandidateWork, dict[str, Any]]] = []
        weak_ranked: list[tuple[CandidateWork, dict[str, Any]]] = []
        rejected_records: list[dict[str, Any]] = []

        for candidate, evidence in ranked:
            candidate_confidence = float(evidence.get("final_score", 0.0) or 0.0)
            candidate_status = self._candidate_classification(candidate_confidence, evidence, has_trusted_title=has_trusted_title)
            if candidate_status == "external_found":
                strong_ranked.append((candidate, evidence))
            elif candidate_status == "external_possible_match":
                possible_ranked.append((candidate, evidence))
            else:
                weak_ranked.append((candidate, evidence))

        for candidate, reasons in rejected:
            rejected_records.append({
                "title": candidate.title,
                "authors": list(candidate.authors or []),
                "year": candidate.year,
                "venue": candidate.venue,
                "doi": candidate.doi,
                "rejection_reasons": list(reasons),
            })

        primary_candidate: tuple[CandidateWork, dict[str, Any]] | None = None
        status = "not_found"
        if strong_ranked:
            primary_candidate = strong_ranked[0]
            status = "external_found"
        elif possible_ranked:
            primary_candidate = possible_ranked[0]
            status = "external_possible_match"
        elif weak_ranked and not is_structured:
            status = "source_degraded" if overall_degraded else "low_confidence"
        elif overall_degraded:
            status = "source_degraded"
        elif is_structured:
            status = "no_reliable_match"

        ordered_records = [*strong_ranked, *possible_ranked]
        for index, (candidate, evidence) in enumerate(ordered_records[:3]):
            candidate_confidence = float(evidence.get("final_score", 0.0) or 0.0)
            candidate_status = self._candidate_classification(candidate_confidence, evidence, has_trusted_title=has_trusted_title)
            record = self._record_from_candidate(
                candidate,
                confidence=candidate_confidence,
                match_status=self._record_match_status(candidate_status, is_top=index == 0),
                evidence=evidence,
            )
            records.append(record)
            if best_record is None and index == 0:
                best_record = record

        for candidate, evidence in weak_ranked[:3]:
            candidate_confidence = float(evidence.get("final_score", 0.0) or 0.0)
            record = self._record_from_candidate(
                candidate,
                confidence=candidate_confidence,
                match_status="low_confidence",
                evidence=evidence,
            )
            low_confidence_records.append(record)

        notes = list(parsed_query.notes)
        if status == "no_reliable_match":
            notes.append("No candidate passed the relevance gate for this structured citation+abstract query.")
            if rejected_records:
                notes.append(f"{len(rejected_records)} candidate(s) were rejected due to insufficient overlap with supplied authors, venue, or strong terms.")
        if overall_degraded and status == "external_found":
            notes.append("Some external sources degraded, but another scholarly source still produced a strong match.")
        elif overall_degraded and status == "source_degraded":
            notes.append("External scholarly lookup was partially degraded and no surviving source produced a strong enough match.")
        elif status == "low_confidence":
            notes.append("The closest external candidates stayed below the verification threshold, so no paper was promoted as the best match.")

        return ScholarlyLookupResult(
            status=status,
            source_mode="external_scholarly",
            records=records,
            best_record=best_record,
            query_terms=self._query_terms_from_reference(ref),
            confidence=round(float((primary_candidate or (ranked[0] if ranked else (None, {"final_score": 0.0})))[1].get("final_score", 0.0) or 0.0), 3),
            confidence_label=self._confidence_label(float((primary_candidate or (ranked[0] if ranked else (None, {"final_score": 0.0})))[1].get("final_score", 0.0) or 0.0)),
            external_search_used=True,
            checked_sources=checked_sources,
            source_diagnostics=source_diagnostics,
            notes=notes,
            low_confidence_records=low_confidence_records,
            source_health=source_health,
            input_reference=parsed_query.input_reference,
            rejected_candidates=rejected_records,
        )

    def _relevance_gate(
        self,
        ranked: list[tuple[CandidateWork, dict[str, Any]]],
        parsed_query: ParsedScholarlyQuery,
    ) -> dict[str, Any]:
        surviving: list[tuple[CandidateWork, dict[str, Any]]] = []
        rejected: list[tuple[CandidateWork, list[str]]] = []

        input_ref = parsed_query.input_reference or {}
        expected_authors = [normalize_author_name(a) for a in (input_ref.get("authors") or [])]
        expected_strong_terms = [t.casefold() for t in (parsed_query.strong_terms or [])]
        expected_year = input_ref.get("year")
        expected_venue = (input_ref.get("venue") or "").casefold()

        for candidate, evidence in ranked:
            reasons: list[str] = []
            candidate_author_keys = set()
            for author in (candidate.authors or []):
                normed = normalize_author_name(author)
                if normed:
                    candidate_author_keys.add(normed)

            author_overlap = sum(1 for ea in expected_authors if ea in candidate_author_keys)
            candidate_title = (candidate.title or "").casefold()
            candidate_abstract = ""
            if candidate.raw:
                abstract = candidate.raw.get("abstract") or ""
                if isinstance(abstract, str):
                    candidate_abstract = abstract.casefold()
            candidate_text = f"{candidate_title} {candidate_abstract}"
            strong_hits = sum(1 for st in expected_strong_terms if st in candidate_text)

            venue_overlap = 0
            if expected_venue and candidate.venue:
                cv = candidate.venue.casefold()
                if expected_venue in cv or cv in expected_venue:
                    venue_overlap = 1

            year_overlap = 0
            if expected_year and candidate.year:
                if abs(int(candidate.year) - int(expected_year)) <= 1:
                    year_overlap = 1

            if author_overlap == 0 and strong_hits == 0 and venue_overlap == 0 and year_overlap == 0:
                reasons.append("No author overlap, no strong-term hits, no venue/year match.")
                rejected.append((candidate, reasons))
                continue

            surviving.append((candidate, evidence))

        surviving.sort(key=lambda item: (
            sum(1 for ea in expected_authors if ea in {normalize_author_name(a) for a in (item[0].authors or [])}),
            sum(1 for st in expected_strong_terms if st in (item[0].title or "").casefold()),
            float(item[1].get("final_score", 0.0) or 0.0),
        ), reverse=True)

        return {"surviving": surviving, "rejected": rejected}

    @staticmethod
    def _normalize_orcid(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        text = re.sub(r"^https?://orcid\.org/", "", text, flags=re.IGNORECASE).strip().strip("/")
        return text or None

    @staticmethod
    def _openalex_author_key(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        text = text.rstrip("/").rsplit("/", 1)[-1]
        return text.upper() if text else None

    @staticmethod
    def _normalized_author_key(name: str) -> str:
        tokens = [token for token in normalize_author_name(name).split() if token]
        if not tokens:
            return ""
        if len(tokens) == 1:
            return tokens[0]
        return " ".join(sorted(tokens))

    @classmethod
    def _author_name_matches(cls, candidate_name: str, target_name: str) -> bool:
        candidate_key = cls._normalized_author_key(candidate_name)
        target_key = cls._normalized_author_key(target_name)
        if not candidate_key or not target_key:
            return False
        if candidate_key == target_key:
            return True
        candidate_tokens = candidate_key.split()
        target_tokens = target_key.split()
        if len(candidate_tokens) >= 2 and len(target_tokens) >= 2:
            return (
                candidate_tokens[-1] == target_tokens[-1]
                and candidate_tokens[0][0] == target_tokens[0][0]
            )
        return False

    @staticmethod
    def _record_is_source_paper(
        record: dict[str, Any],
        *,
        exclude_doi: str | None,
        exclude_title: str | None,
    ) -> bool:
        record_doi = normalize_doi(str(record.get("doi") or "")) if record.get("doi") else None
        if exclude_doi and record_doi and record_doi == exclude_doi:
            return True
        record_title = normalize_title(str(record.get("title") or ""))
        return bool(exclude_title and record_title and record_title == exclude_title)

    @classmethod
    def _dedupe_publication_records(
        cls,
        records: list[dict[str, Any]],
        *,
        exclude_doi: str | None,
        exclude_title: str | None,
    ) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for record in records:
            if cls._record_is_source_paper(record, exclude_doi=exclude_doi, exclude_title=exclude_title):
                continue
            doi_key = normalize_doi(str(record.get("doi") or "")) if record.get("doi") else ""
            title_key = normalize_title(str(record.get("title") or ""))
            key = (doi_key, title_key)
            if not any(key):
                continue
            if key in seen:
                continue
            seen.add(key)
            deduped.append(record)
        return deduped

    def _search_internal_author_publications(
        self,
        db: Session,
        *,
        author_name: str,
        author_orcid: str | None,
        exclude_doi: str | None,
        exclude_title: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        normalized_name = author_name.casefold().strip()
        if not normalized_name:
            return [], self._checked_source("internal", "skipped", detail="No author name was available for internal lookup.")

        query = (
            db.query(Article)
            .join(Article.authors)
            .options(selectinload(Article.authors), selectinload(Article.venue))
            .filter(func.lower(ArticleAuthor.full_name) == normalized_name)
            .order_by(Article.publication_year.desc())
            .limit(max(limit * 3, 10))
        )
        records: list[dict[str, Any]] = []
        for article in query.all():
            article_authors = list(getattr(article, "authors", []) or [])
            matched_author = next(
                (
                    item
                    for item in article_authors
                    if self._author_name_matches(str(item.full_name or ""), author_name)
                ),
                None,
            )
            if matched_author is None:
                continue
            confidence = 0.96 if author_orcid and self._normalize_orcid(getattr(matched_author, "orcid", None)) == author_orcid else 0.78
            record = {
                "title": article.title,
                "authors": [str(item.full_name) for item in article_authors if getattr(item, "full_name", None)],
                "year": article.publication_year,
                "venue": article.venue.title if getattr(article, "venue", None) is not None else None,
                "doi": article.doi,
                "abstract": article.abstract,
                "url": article.url,
                "source": _SOURCE_LABELS["internal"],
                "confidence": round(confidence, 3),
                "match_status": "author_orcid_match" if confidence >= 0.95 else "author_name_match",
                "subjects": [],
                "keywords": [],
            }
            if self._record_is_source_paper(record, exclude_doi=exclude_doi, exclude_title=exclude_title):
                continue
            records.append(record)

        records = self._dedupe_publication_records(records, exclude_doi=exclude_doi, exclude_title=exclude_title)[:limit]
        state = "matched" if records else "no_match"
        detail = (
            f"Found {len(records)} internal publications for author {author_name}."
            if records
            else f"No internal publications matched author {author_name} beyond the source paper."
        )
        return records, self._checked_source("internal", state, detail=detail, candidate_count=len(records))

    def _resolve_openalex_author(
        self,
        *,
        name: str,
        orcid: str | None,
        openalex_id: str | None,
    ) -> tuple[str | None, dict[str, Any], list[str], float | None]:
        notes: list[str] = []
        if openalex_id:
            return (
                self._openalex_author_key(openalex_id),
                self._checked_source("openalex", "matched", detail="Reused OpenAlex author ID from the resolved source paper.", candidate_count=1),
                notes,
                0.98,
            )

        if not settings.openalex_enabled:
            return None, self._checked_source("openalex", "disabled", detail="OpenAlex author lookup is disabled."), notes, None

        headers = {"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"}
        params: dict[str, Any]
        detail = None
        try:
            if orcid:
                params = {"filter": f"orcid:{orcid}", "per-page": 3}
                detail = f"Resolved OpenAlex author candidates by ORCID {orcid}."
            else:
                params = {"search": name, "per-page": 5}
                detail = f"Resolved OpenAlex author candidates by name search for {name}."

            response = self._http_get(OPENALEX_AUTHORS_URL, params=params, headers=headers)
            results = response.json().get("results", [])
            if not results:
                return None, self._checked_source("openalex", "no_match", detail=detail, candidate_count=0), notes, None

            normalized_target = self._normalized_author_key(name)
            exact_matches = [
                item
                for item in results
                if self._normalized_author_key(str(item.get("display_name") or "")) == normalized_target
            ]
            candidates = exact_matches or [item for item in results if str(item.get("display_name") or "").strip()]
            candidates.sort(key=lambda item: int(item.get("works_count") or 0), reverse=True)
            selected = candidates[0] if candidates else None
            if not isinstance(selected, dict) or not selected.get("id"):
                return None, self._checked_source("openalex", "no_match", detail=detail, candidate_count=len(results)), notes, None

            if not orcid and len(exact_matches) > 1:
                notes.append("Multiple OpenAlex author profiles share this display name; the highest-works-count profile was selected as a fallback.")
                confidence = 0.68
            elif orcid:
                confidence = 0.95
            else:
                confidence = 0.82 if exact_matches else 0.6
                if not exact_matches:
                    notes.append("OpenAlex author profile was selected from a name search without an exact ORCID match.")

            return (
                self._openalex_author_key(selected.get("id")),
                self._checked_source("openalex", "matched", detail=detail, candidate_count=len(results)),
                notes,
                confidence,
            )
        except httpx.TimeoutException:
            return None, self._checked_source("openalex", "timeout", detail="OpenAlex author lookup timed out."), notes, None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            state = "rate_limited" if status == 429 else "http_error"
            return None, self._checked_source("openalex", state, detail=f"HTTP {status}"), notes, None
        except httpx.RequestError as exc:
            return None, self._checked_source("openalex", "error", detail=str(exc)), notes, None
        except (ValueError, TypeError) as exc:
            return None, self._checked_source("openalex", "error", detail=str(exc)), notes, None

    def _search_openalex_author_works(
        self,
        author_id: str,
        *,
        limit: int,
    ) -> tuple[list[CandidateWork], dict[str, Any]]:
        if not settings.openalex_enabled:
            return [], {"state": "disabled", "candidate_count": 0, "detail": "OpenAlex author works lookup is disabled."}

        author_key = self._openalex_author_key(author_id)
        if not author_key:
            return [], {"state": "skipped", "candidate_count": 0, "detail": "No OpenAlex author ID was available."}

        try:
            response = self._http_get(
                OPENALEX_WORKS_URL,
                params={"filter": f"author.id:{author_key}", "sort": "-publication_date", "per-page": max(1, min(limit, 25))},
                headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
            )
            items = response.json().get("results", [])
            candidates = [normalize_openalex_work(item) for item in items if isinstance(item, dict)]
            state = "matched" if candidates else "no_match"
            detail = "OpenAlex author works lookup returned candidates." if candidates else "OpenAlex author works lookup returned no candidates."
            return candidates, {"state": state, "candidate_count": len(candidates), "detail": detail}
        except httpx.TimeoutException:
            return [], {"state": "timeout", "candidate_count": 0, "detail": "Request timed out."}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            state = "rate_limited" if status == 429 else "http_error"
            return [], {"state": state, "candidate_count": 0, "detail": f"HTTP {status}"}
        except httpx.RequestError as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}
        except (ValueError, TypeError) as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}

    def _search_crossref_author_works(
        self,
        author_name: str,
        *,
        limit: int,
    ) -> tuple[list[CandidateWork], dict[str, Any]]:
        if not settings.crossref_enabled:
            return [], {"state": "disabled", "candidate_count": 0, "detail": "Crossref author works lookup is disabled."}

        if not author_name.strip():
            return [], {"state": "skipped", "candidate_count": 0, "detail": "No author name was available for Crossref lookup."}

        try:
            response = self._http_get(
                CROSSREF_WORKS_URL,
                params={"query.author": author_name, "rows": max(1, min(limit, 25))},
                headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
            )
            items = response.json().get("message", {}).get("items", [])
            candidates = [normalize_crossref_work(item) for item in items if isinstance(item, dict)]
            state = "matched" if candidates else "no_match"
            detail = "Crossref author lookup returned candidates." if candidates else "Crossref author lookup returned no candidates."
            return candidates, {"state": state, "candidate_count": len(candidates), "detail": detail}
        except httpx.TimeoutException:
            return [], {"state": "timeout", "candidate_count": 0, "detail": "Request timed out."}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            state = "rate_limited" if status == 429 else "http_error"
            return [], {"state": state, "candidate_count": 0, "detail": f"HTTP {status}"}
        except httpx.RequestError as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}
        except (ValueError, TypeError) as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}

    def _search_web_author_publications(
        self,
        author_name: str,
        *,
        source_title: str | None,
        exclude_doi: str | None,
        exclude_title: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
        if not author_name.strip():
            return [], {"state": "skipped", "candidate_count": 0, "detail": "No author name was available for web search fallback."}, []
        if settings.web_search_provider == "disabled":
            return [], {"state": "disabled", "candidate_count": 0, "detail": "Web search fallback is disabled."}, []

        hits, context = _WEB_SEARCH_SOURCE.search_author_publications_with_context(
            author_name,
            source_title=source_title,
            limit=max(1, min(limit, 8)),
            provider=getattr(settings, "web_search_provider", None),
            api_key=getattr(settings, "web_search_api_key", None),
            endpoint=getattr(settings, "web_search_endpoint", None),
            timeout=getattr(settings, "external_search_timeout_seconds", None),
            tavily_api_key=getattr(settings, "tavily_api_key", None),
            tavily_endpoint=getattr(settings, "tavily_search_endpoint", None),
            tavily_search_depth=getattr(settings, "tavily_search_depth", None),
            tavily_max_results=getattr(settings, "tavily_max_results", limit),
            tavily_include_answer=getattr(settings, "tavily_include_answer", False),
            tavily_include_raw_content=getattr(settings, "tavily_include_raw_content", False),
            tavily_timeout_seconds=getattr(settings, "tavily_timeout_seconds", None),
        )

        state = str(context.get("state") or "unknown")
        if state != "matched":
            return [], {
                "state": state,
                "candidate_count": 0,
                "detail": str(context.get("detail")) if context.get("detail") else None,
            }, []

        verified_records: list[dict[str, Any]] = []
        notes: list[str] = []
        seen_dois: set[str] = set()
        provider = str(context.get("provider") or settings.web_search_provider or "web_search")
        query = str(context.get("query") or "").strip()

        for hit in hits:
            doi_candidates = [
                normalize_doi(str(raw_doi))
                for raw_doi in [
                    hit.doi,
                    *(
                        hit.raw.get("doi_candidates", [])
                        if isinstance(hit.raw.get("doi_candidates"), list)
                        else []
                    ),
                ]
                if str(raw_doi or "").strip()
            ]
            for doi in doi_candidates[:2]:
                if not doi or doi in seen_dois:
                    continue
                seen_dois.add(doi)
                exact_result = citation_checker.verify_doi_exact(doi, citation_context={"raw": hit.title or doi})
                if exact_result.status != "DOI_VERIFIED":
                    continue
                record = self._record_from_exact_result(exact_result)
                if not any(self._author_name_matches(candidate_author, author_name) for candidate_author in record.get("authors") or []):
                    continue
                if self._record_is_source_paper(record, exclude_doi=exclude_doi, exclude_title=exclude_title):
                    continue
                evidence_urls = self._dedupe_strings([
                    *(record.get("evidence_urls") or []),
                    *(hit.evidence_urls or []),
                ])
                record["evidence_urls"] = evidence_urls
                record["resolved_url"] = record.get("resolved_url") or hit.url
                record["url"] = record.get("url") or hit.url
                verified_records.append(record)

        if not verified_records:
            detail = "Web search returned results, but none could be re-verified to a DOI-backed publication for this author."
            if query:
                detail = f'{detail} Query: "{query}".'
            return [], {"state": "no_match", "candidate_count": 0, "detail": detail}, notes

        detail = f"Web search ({provider}) discovered {len(verified_records)} DOI-backed author publications."
        if query:
            detail = f'{detail} Query: "{query}".'
        return verified_records, {"state": "matched", "candidate_count": len(verified_records), "detail": detail}, notes

    @staticmethod
    def _merge_checked_sources(
        existing: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rank = {
            "matched": 5,
            "low_confidence": 4,
            "no_match": 3,
            "skipped": 2,
            "disabled": 1,
            "timeout": 0,
            "rate_limited": 0,
            "http_error": 0,
            "error": 0,
        }
        merged = {str(item.get("name") or ""): dict(item) for item in existing if item.get("name")}
        for item in incoming:
            name = str(item.get("name") or "")
            if not name:
                continue
            current = merged.get(name)
            current_rank = rank.get(str((current or {}).get("state") or "").lower(), -1)
            new_rank = rank.get(str(item.get("state") or "").lower(), -1)
            if current is None or new_rank > current_rank:
                merged[name] = dict(item)
        return list(merged.values())

    def _lookup_exact_identifier(self, text: str) -> ScholarlyLookupResult | None:
        exact_identifiers = citation_checker.extract_exact_identifiers(text)
        citation_context = {"raw": text}

        doi = next(iter(citation_checker.extract_dois(text)), None)
        if doi:
            result = citation_checker.verify_doi_exact(doi, citation_context=citation_context)
            if result.status == "NO_CITATION_FOUND":
                return None
            checked_sources = self._checked_sources_from_diagnostics(result.source_diagnostics)
            record = self._record_from_exact_result(result) if result.status == "DOI_VERIFIED" else None
            status = "external_found" if result.status == "DOI_VERIFIED" else "not_found"
            notes = [note for note in [result.warning, result.reason] if note]
            return ScholarlyLookupResult(
                status=status,
                source_mode="external_scholarly",
                records=[record] if record else [],
                best_record=record,
                query_terms=[normalize_doi(doi)],
                confidence=float(record.get("confidence", 1.0) if record else 0.0),
                confidence_label=self._confidence_label(float(record.get("confidence", 1.0))) if record else None,
                external_search_used=True,
                checked_sources=checked_sources,
                source_diagnostics=result.source_diagnostics,
                notes=notes,
            )

        if not exact_identifiers:
            return None

        identifier = exact_identifiers[0]
        result = citation_checker.verify_identifier_exact(
            str(identifier.get("identifier") or identifier.get("exact_raw") or identifier.get("raw") or ""),
            str(identifier.get("identifier_type") or ""),
            citation_context=citation_context,
        )
        if result.status == "NO_CITATION_FOUND":
            return None

        checked_sources = self._checked_sources_from_diagnostics(result.source_diagnostics)
        record = self._record_from_exact_result(result) if result.status == "IDENTIFIER_VERIFIED" else None
        status = "external_found" if result.status == "IDENTIFIER_VERIFIED" else "not_found"
        notes = [note for note in [result.warning, result.reason] if note]
        return ScholarlyLookupResult(
            status=status,
            source_mode="external_scholarly",
            records=[record] if record else [],
            best_record=record,
            query_terms=[str(identifier.get("identifier") or "")],
            confidence=float(record.get("confidence", 1.0) if record else 0.0),
            confidence_label=self._confidence_label(float(record.get("confidence", 1.0))) if record else None,
            external_search_used=True,
            checked_sources=checked_sources,
            source_diagnostics=result.source_diagnostics,
            notes=notes,
        )

    def _parse_query(self, text: str) -> ParsedScholarlyQuery:
        citation_abstract = self._parse_paper_lookup_from_citation_and_abstract(text)
        if citation_abstract is not None:
            return citation_abstract

        header = self._parse_paper_header(text)
        if header is not None:
            return header

        parsed = parse_reference_metadata(text)
        notes: list[str] = []
        if parsed.title and (parsed.authors or parsed.year is not None or parsed.venue):
            search_queries = self._build_search_variants(parsed.title, parsed.authors, parsed.year, parsed.venue)
            return ParsedScholarlyQuery(
                reference=parsed,
                notes=["Resolved the lookup query from the supplied title/reference metadata."],
                query_hint=" ".join(part for part in [parsed.title, " ".join(parsed.authors)] if part).strip() or parsed.title,
                query_type=_QUERY_TYPE_TITLE_KNOWN if parsed.title else _QUERY_TYPE_GENERIC,
                search_queries=search_queries,
                strong_terms=self._extract_strong_terms(parsed.title if parsed.title else "", [parsed.venue or "", *(parsed.authors or [])]),
                input_reference=self._build_input_reference(parsed),
            )

        fallback_title = build_fallback_title_query(text, parsed)
        if fallback_title:
            ref = ReferenceMetadata(
                raw=text,
                title=fallback_title,
                authors=list(parsed.authors or []),
                year=parsed.year,
                venue=parsed.venue,
                volume=parsed.volume,
                issue=parsed.issue,
                pages=parsed.pages,
                doi=parsed.doi,
                confidence=max(parsed.confidence, 0.45),
            )
            notes.append("Fell back to a title-like phrase extracted from the supplied text.")
            search_queries = self._build_search_variants(fallback_title, parsed.authors, parsed.year, parsed.venue)
            return ParsedScholarlyQuery(
                reference=ref,
                notes=notes,
                query_hint=fallback_title,
                query_type=_QUERY_TYPE_TITLE_KNOWN if fallback_title else _QUERY_TYPE_GENERIC,
                search_queries=search_queries,
                strong_terms=self._extract_strong_terms(fallback_title, [parsed.venue or "", *(parsed.authors or [])]),
                input_reference=self._build_input_reference(ref),
            )

        return ParsedScholarlyQuery(
            reference=ReferenceMetadata(raw=text, title=text.strip(), confidence=0.30),
            notes=["Used the raw user text as the lookup query because structured metadata could not be extracted."],
            query_hint=text.strip(),
            query_type=_QUERY_TYPE_GENERIC,
            search_queries=[text.strip()],
            strong_terms=self._extract_strong_terms(text),
            input_reference={"raw": text.strip()},
        )

    def _parse_paper_lookup_from_citation_and_abstract(self, text: str) -> ParsedScholarlyQuery | None:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if len(lines) < 3:
            return None

        first_line = lines[0]
        second_line = lines[1]

        is_author_list = bool(_SEMICOLON_AUTHOR_RE.match(first_line) or _COMMA_AUTHOR_RE.match(first_line))
        if not is_author_list:
            return None

        has_venue_metadata = bool(_VENUE_LINE_RE.search(second_line))
        if not has_venue_metadata:
            return None

        authors = self._parse_author_list(first_line)
        if len(authors) < 2:
            return None

        year, venue_name, venue_location = self._parse_venue_line(second_line)

        abstract_lines = lines[2:]
        abstract_text = " ".join(abstract_lines)

        strong_terms = self._extract_strong_terms(abstract_text, [first_line, second_line])

        input_reference = {
            "query_type": _QUERY_TYPE_CITATION_ABSTRACT,
            "authors": authors,
            "venue": venue_name or second_line,
            "year": year,
            "location": venue_location,
            "strong_terms": strong_terms,
            "abstract_excerpt": abstract_text[:200] if abstract_text else None,
        }

        search_queries = self._build_citation_abstract_queries(authors, year, venue_name, strong_terms)

        ref = ReferenceMetadata(
            raw=text,
            title=None,
            authors=authors,
            year=year,
            venue=venue_name or second_line,
            confidence=0.70,
        )

        notes_parts = ["Detected an authors-first citation with abstract layout."]
        if year:
            notes_parts.append(f"Year: {year}")
        if venue_name:
            notes_parts.append(f"Venue: {venue_name}")

        return ParsedScholarlyQuery(
            reference=ref,
            notes=["; ".join(notes_parts)],
            query_hint=search_queries[0] if search_queries else " ".join(authors),
            query_type=_QUERY_TYPE_CITATION_ABSTRACT,
            search_queries=search_queries,
            strong_terms=strong_terms,
            input_reference=input_reference,
        )

    @staticmethod
    def _parse_author_list(line: str) -> list[str]:
        cleaned = re.sub(r"\d+", "", line)
        parts = re.split(r"[;]", cleaned)
        authors: list[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            sub_parts = [sp.strip() for sp in part.split(",") if sp.strip()]
            if len(sub_parts) == 2:
                name = f"{sub_parts[1].strip()} {sub_parts[0].strip()}"
            else:
                name = part
            name = re.sub(r"\s+", " ", name).strip().strip(".,;:")
            if name and len(name) > 2:
                authors.append(name)
        return authors

    @staticmethod
    def _parse_venue_line(line: str) -> tuple[int | None, str | None, str | None]:
        year = None
        venue_name = None
        venue_location = None

        year_match = re.search(r"\b((?:19|20)\d{2})\b", line)
        if year_match:
            year = int(year_match.group(1))

        # Try to find venue acronym (like ECCE 2005, ICSE 2024)
        venue_acronym_match = re.search(
            r"\b([A-Z]{2,}(?:\s+\d{4})?)\b", line
        )
        if venue_acronym_match:
            venue_name = venue_acronym_match.group(1)
            # Check for location after acronym
            after_acro = line[venue_acronym_match.end():].strip().strip(",")
            if after_acro:
                # Try to extract location (words before year pattern)
                location_match = re.search(
                    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s*,?\s*(?:19|20)\d{2}", after_acro
                )
                if location_match:
                    venue_location = location_match.group(1).strip()
                elif not venue_location:
                    venue_location = after_acro

        return year, venue_name, venue_location

    @staticmethod
    def _build_citation_abstract_queries(
        authors: list[str], year: int | None, venue: str | None, strong_terms: list[str]
    ) -> list[str]:
        queries: list[str] = []
        quoted_authors = [f'"{a}"' for a in authors[:3]]
        quoted_strong = [f'"{t}"' for t in strong_terms[:3]]

        if strong_terms and authors:
            q_parts = [quoted_strong[0], *quoted_authors[:2]]
            if year:
                q_parts.append(str(year))
            queries.append(" ".join(q_parts))

        if len(strong_terms) >= 2:
            queries.append(f"{quoted_strong[0]} {quoted_strong[1]}")

        if len(authors) >= 2:
            q_parts = quoted_authors[:3]
            if venue:
                venue_acronym = re.match(r"([A-Z]{2,})", venue)
                if venue_acronym:
                    q_parts.append(venue_acronym.group(1))
            if year:
                q_parts.append(str(year))
            queries.append(" ".join(q_parts))

        if venue and strong_terms:
            queries.append(f'"{venue}" {quoted_strong[0]}')

        return queries

    @staticmethod
    def _build_search_variants(
        title: str | None, authors: list[str] | None, year: int | None, venue: str | None
    ) -> list[str]:
        queries: list[str] = []
        if title:
            queries.append(title.strip())
            if authors:
                queries.append(f'"{title.strip()}" {" ".join(authors[:2])}')
        if authors:
            auth_str = " ".join(authors[:2])
            if year:
                queries.append(f"{auth_str} {year}")
        return queries

    @staticmethod
    def _build_input_reference(ref: ReferenceMetadata) -> dict[str, Any]:
        return {
            "query_type": _QUERY_TYPE_TITLE_KNOWN if ref.title else _QUERY_TYPE_GENERIC,
            "title_hint": ref.title,
            "authors": ref.authors,
            "year": ref.year,
            "venue": ref.venue,
            "doi": ref.doi,
        }

    @staticmethod
    def _parse_paper_header(text: str) -> ParsedScholarlyQuery | None:
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if len(lines) < 2:
            return None

        first_line = lines[0].strip()
        second_line = lines[1].strip()

        if _SEMICOLON_AUTHOR_RE.match(first_line) or _COMMA_AUTHOR_RE.match(first_line):
            return None
        if _VENUE_LINE_RE.search(second_line):
            return None

        title = first_line
        author_line = second_line
        if len(title) < 16 or len(title) > 320:
            return None
        if _PAPER_HEADER_AFFILIATION_RE.search(author_line):
            return None

        cleaned_author_line = re.sub(r"(?<=[A-Za-z])\d+(?=(?:[,;\s]|$))", "", author_line)
        authors = _PAPER_HEADER_AUTHOR_RE.findall(cleaned_author_line)
        if not authors:
            return None

        ref = ReferenceMetadata(
            raw=text,
            title=title,
            authors=authors,
            confidence=0.82,
        )
        query_hint = " ".join(part for part in [title, cleaned_author_line] if part).strip()
        return ParsedScholarlyQuery(
            reference=ref,
            notes=["Resolved the lookup query from a pasted paper header (title + author line)."],
            query_hint=query_hint,
            query_type=_QUERY_TYPE_TITLE_KNOWN,
            search_queries=[title.strip()],
            strong_terms=ExternalAcademicSearchService._extract_strong_terms(title, [cleaned_author_line]),
            input_reference={"query_type": _QUERY_TYPE_TITLE_KNOWN, "title_hint": title, "authors": authors},
        )

    def _search_crossref(self, ref: ReferenceMetadata, limit: int = 5, parsed_query: ParsedScholarlyQuery | None = None) -> tuple[list[CandidateWork], dict[str, Any]]:
        if not settings.crossref_enabled:
            return [], {"state": "disabled", "candidate_count": 0, "detail": "Crossref search is disabled."}
        params: dict[str, Any] = {"rows": limit}
        if parsed_query and parsed_query.query_type == _QUERY_TYPE_CITATION_ABSTRACT:
            params["query.bibliographic"] = ref.title.strip() if ref.title else (parsed_query.search_queries[0] if parsed_query.search_queries else ref.raw)
        elif ref.title:
            params["query.title"] = ref.title.strip()
        else:
            params["query"] = ref.raw
        if ref.authors:
            params["query.author"] = ref.authors[0]
        if ref.year:
            params["filter"] = f"from-pub-date:{ref.year},until-pub-date:{ref.year}"

        try:
            response = self._http_get(
                CROSSREF_WORKS_URL,
                params=params,
                headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
            )
            items = response.json().get("message", {}).get("items", [])
            candidates = [normalize_crossref_work(item) for item in items if isinstance(item, dict)]
            state = "matched" if candidates else "no_match"
            detail = "Crossref title-specific search matched candidates." if candidates else "Crossref title-specific search returned no candidates."
            return candidates, {"state": state, "candidate_count": len(candidates), "detail": detail}
        except httpx.TimeoutException:
            return [], {"state": "timeout", "candidate_count": 0, "detail": "Request timed out."}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            state = "rate_limited" if status == 429 else "http_error"
            return [], {"state": state, "candidate_count": 0, "detail": f"HTTP {status}"}
        except httpx.RequestError as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}
        except (ValueError, TypeError) as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}

    def _search_openalex(self, ref: ReferenceMetadata, limit: int = 5, parsed_query: ParsedScholarlyQuery | None = None) -> tuple[list[CandidateWork], dict[str, Any]]:
        if not settings.openalex_enabled:
            return [], {"state": "disabled", "candidate_count": 0, "detail": "OpenAlex search is disabled."}
        query = (ref.title or "").strip()
        if parsed_query and parsed_query.query_type == _QUERY_TYPE_CITATION_ABSTRACT:
            if not query:
                query = parsed_query.search_queries[0] if parsed_query.search_queries else ""
            if not query:
                return [], {"state": "skipped", "candidate_count": 0, "detail": "No search query was available for OpenAlex citation+abstract lookup."}
            try:
                response = self._http_get(
                    OPENALEX_WORKS_URL,
                    params={"search": query, "per-page": limit},
                    headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
                )
                items = response.json().get("results", [])
                candidates = [normalize_openalex_work(item) for item in items if isinstance(item, dict)]
                state = "matched" if candidates else "no_match"
                detail = "OpenAlex search matched candidates." if candidates else "OpenAlex search returned no candidates."
                return candidates, {"state": state, "candidate_count": len(candidates), "detail": detail}
            except httpx.TimeoutException:
                return [], {"state": "timeout", "candidate_count": 0, "detail": "Request timed out."}
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else "unknown"
                state = "rate_limited" if status == 429 else "http_error"
                return [], {"state": state, "candidate_count": 0, "detail": f"HTTP {status}"}
            except httpx.RequestError as exc:
                return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}
            except (ValueError, TypeError) as exc:
                return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}

        if not query:
            return [], {"state": "skipped", "candidate_count": 0, "detail": "No title-like query was available for OpenAlex search."}

        filter_parts = [f"title.search.exact:{query}"]
        if ref.authors:
            filter_parts.append(f'raw_author_name.search:"{ref.authors[0]}"')
        try:
            response = self._http_get(
                OPENALEX_WORKS_URL,
                params={"filter": ",".join(filter_parts), "per-page": limit},
                headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
            )
            items = response.json().get("results", [])
            candidates = [normalize_openalex_work(item) for item in items if isinstance(item, dict)]
            if candidates:
                return candidates, {
                    "state": "matched",
                    "candidate_count": len(candidates),
                    "detail": "OpenAlex exact-title search matched candidates.",
                }
            fallback_query = query.rstrip("?.!,:; ")
            if not fallback_query:
                return [], {"state": "no_match", "candidate_count": 0, "detail": "OpenAlex exact-title search returned no candidates."}
            response = self._http_get(
                OPENALEX_WORKS_URL,
                params={"search": fallback_query, "per-page": limit},
                headers={"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"},
            )
            items = response.json().get("results", [])
            candidates = [normalize_openalex_work(item) for item in items if isinstance(item, dict)]
            state = "matched" if candidates else "no_match"
            detail = (
                "OpenAlex exact-title search returned no candidates; fallback search matched candidates."
                if candidates
                else "OpenAlex exact-title and fallback search returned no candidates."
            )
            return candidates, {"state": state, "candidate_count": len(candidates), "detail": detail}
        except httpx.TimeoutException:
            return [], {"state": "timeout", "candidate_count": 0, "detail": "Request timed out."}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            state = "rate_limited" if status == 429 else "http_error"
            return [], {"state": state, "candidate_count": 0, "detail": f"HTTP {status}"}
        except httpx.RequestError as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}
        except (ValueError, TypeError) as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}

    def _search_pubmed(
        self,
        ref: ReferenceMetadata,
        *,
        preferred_doi: str | None = None,
        limit: int = 5,
    ) -> tuple[list[CandidateWork], dict[str, Any]]:
        if not settings.pubmed_enabled:
            return [], {"state": "disabled", "candidate_count": 0, "detail": "PubMed fallback is disabled."}

        query = self._build_pubmed_query(ref, preferred_doi=preferred_doi)
        if not query:
            return [], {"state": "skipped", "candidate_count": 0, "detail": "No PubMed-compatible query could be built."}

        headers = {"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"}
        search_params: dict[str, Any] = {
            "db": "pubmed",
            "retmode": "json",
            "retmax": max(1, min(limit, 10)),
            "sort": "relevance",
            "term": query,
        }
        if settings.pubmed_api_key:
            search_params["api_key"] = settings.pubmed_api_key

        try:
            response = self._http_get(_PUBMED_SEARCH_URL, params=search_params, headers=headers)
            payload = response.json().get("esearchresult", {})
            ids = [str(item).strip() for item in payload.get("idlist", []) if str(item).strip()]
            if not ids:
                return [], {"state": "no_match", "candidate_count": 0, "detail": "PubMed search returned no candidates."}

            summary_params: dict[str, Any] = {
                "db": "pubmed",
                "retmode": "json",
                "id": ",".join(ids[:limit]),
            }
            if settings.pubmed_api_key:
                summary_params["api_key"] = settings.pubmed_api_key
            summary = self._http_get(_PUBMED_SUMMARY_URL, params=summary_params, headers=headers)
            results = summary.json().get("result", {})
            candidates = [
                self._normalize_pubmed_work(results.get(pmid), pmid)
                for pmid in ids[:limit]
                if isinstance(results.get(pmid), dict)
            ]
            candidates = [candidate for candidate in candidates if candidate is not None]
            if not candidates:
                return [], {"state": "no_match", "candidate_count": 0, "detail": "PubMed returned identifiers, but no usable metadata candidates."}
            detail = "PubMed DOI lookup matched candidates." if preferred_doi else "PubMed tokenized title/author search matched candidates."
            return candidates, {"state": "matched", "candidate_count": len(candidates), "detail": detail}
        except httpx.TimeoutException:
            return [], {"state": "timeout", "candidate_count": 0, "detail": "Request timed out."}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            state = "rate_limited" if status == 429 else "http_error"
            return [], {"state": state, "candidate_count": 0, "detail": f"HTTP {status}"}
        except httpx.RequestError as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}
        except (ValueError, TypeError) as exc:
            return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}

    def _search_semantic_scholar(self, ref: ReferenceMetadata, limit: int = 5, parsed_query: ParsedScholarlyQuery | None = None) -> tuple[list[CandidateWork], dict[str, Any]]:
        if not settings.semantic_scholar_enabled:
            return [], {"state": "disabled", "candidate_count": 0, "detail": "Semantic Scholar fallback is disabled."}
        query = (ref.title or "").strip()
        if parsed_query and parsed_query.query_type == _QUERY_TYPE_CITATION_ABSTRACT and parsed_query.search_queries:
            query = parsed_query.search_queries[0]
        if not query:
            return [], {"state": "skipped", "candidate_count": 0, "detail": "No title-like query was available for Semantic Scholar search."}

        headers = {"User-Agent": "AIRA/1.0 (mailto:aira@research.local)"}
        if settings.semantic_scholar_api_key:
            headers["x-api-key"] = settings.semantic_scholar_api_key

        params = {
            "query": query,
            "limit": max(1, min(limit, 10)),
            "fields": _SEMANTIC_SCHOLAR_LOOKUP_FIELDS,
        }
        attempts = max(0, settings.semantic_scholar_retry_count) + 1
        for attempt in range(attempts):
            try:
                response = self._http_get(
                    SEMANTIC_SCHOLAR_SEARCH_URL,
                    params=params,
                    headers=headers,
                )
                payload = response.json()
                raw_papers = payload.get("data", []) if isinstance(payload, dict) else []
                candidates = [
                    candidate
                    for paper in raw_papers
                    if isinstance(paper, dict)
                    for candidate in [normalize_semantic_scholar_paper(paper)]
                    if candidate is not None
                ]
                state = "matched" if candidates else "no_match"
                return candidates, {"state": state, "candidate_count": len(candidates), "detail": None}
            except httpx.TimeoutException:
                return [], {"state": "timeout", "candidate_count": 0, "detail": "Request timed out."}
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code if exc.response is not None else "unknown"
                retryable = status == 429 or 500 <= int(status) < 600 if isinstance(status, int) else False
                if retryable and attempt + 1 < attempts:
                    time.sleep(settings.semantic_scholar_retry_backoff_ms / 1000)
                    continue
                state = "rate_limited" if status == 429 else "http_error"
                return [], {"state": state, "candidate_count": 0, "detail": f"HTTP {status}"}
            except httpx.RequestError as exc:
                return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}
            except (ValueError, TypeError) as exc:
                return [], {"state": "error", "candidate_count": 0, "detail": str(exc)}
        return [], {"state": "error", "candidate_count": 0, "detail": "Semantic Scholar fallback failed unexpectedly."}

    @staticmethod
    def _http_get(url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None) -> httpx.Response:
        with httpx.Client(timeout=settings.external_search_timeout_seconds) as client:
            response = client.get(url, params=params, headers=headers or {})
        response.raise_for_status()
        return response

    @staticmethod
    def _merge_candidates(*candidate_groups: list[CandidateWork]) -> list[CandidateWork]:
        merged: list[CandidateWork] = []
        doi_index: dict[str, CandidateWork] = {}
        external_index: dict[tuple[str, str], CandidateWork] = {}
        title_year_index: dict[tuple[str, int | None], CandidateWork] = {}

        def add(candidate: CandidateWork) -> None:
            existing: CandidateWork | None = None
            if candidate.doi:
                doi_key = normalize_doi(candidate.doi)
                existing = doi_index.get(doi_key)
                if existing is not None:
                    ExternalAcademicSearchService._enrich_candidate(existing, candidate)
                    return
            if candidate.external_id:
                external_key = ((candidate.external_id_type or candidate.source).lower(), candidate.external_id.lower())
                existing = external_index.get(external_key)
                if existing is not None:
                    ExternalAcademicSearchService._enrich_candidate(existing, candidate)
                    return
            if candidate.title:
                title_key = normalize_title(candidate.title)
                title_year_key = (title_key, candidate.year)
                if title_key:
                    existing = title_year_index.get(title_year_key)
                    if existing is not None:
                        ExternalAcademicSearchService._enrich_candidate(existing, candidate)
                        return
            merged.append(candidate)
            if candidate.doi:
                doi_index[normalize_doi(candidate.doi)] = candidate
            if candidate.external_id:
                external_index[((candidate.external_id_type or candidate.source).lower(), candidate.external_id.lower())] = candidate
            if candidate.title:
                title_key = normalize_title(candidate.title)
                if title_key:
                    title_year_index[(title_key, candidate.year)] = candidate

        for group in candidate_groups:
            for candidate in group:
                add(candidate)
        return merged

    @staticmethod
    def _enrich_candidate(existing: CandidateWork, incoming: CandidateWork) -> None:
        for field_name in ("title", "year", "venue", "doi", "url", "external_id", "external_id_type", "volume", "issue", "pages", "pmid", "pmcid", "resolved_url"):
            if getattr(existing, field_name, None) in (None, "") and getattr(incoming, field_name, None) not in (None, ""):
                setattr(existing, field_name, getattr(incoming, field_name))
        if incoming.authors:
            existing_authors = list(existing.authors or [])
            existing_keys: set[str] = set()
            for author in existing_authors:
                key = normalize_author_name(author) or author.casefold()
                existing_keys.add(key)
            for author in incoming.authors:
                key = normalize_author_name(author) or author.casefold()
                if key not in existing_keys:
                    existing_authors.append(author)
                    existing_keys.add(key)
            existing.authors = existing_authors
        if incoming.evidence_urls:
            seen = {url for url in existing.evidence_urls if url}
            for url in incoming.evidence_urls:
                if url and url not in seen:
                    existing.evidence_urls.append(url)
                    seen.add(url)
        if incoming.raw and not existing.raw:
            existing.raw = dict(incoming.raw)

    @staticmethod
    def _rank_candidates(ref: ReferenceMetadata, candidates: list[CandidateWork]) -> list[tuple[CandidateWork, dict[str, Any]]]:
        ranked = [(candidate, compare_reference_to_candidate(ref, candidate)) for candidate in candidates]
        ranked.sort(key=lambda item: float(item[1].get("final_score", 0.0) or 0.0), reverse=True)
        return ranked

    @staticmethod
    @staticmethod
    def _candidate_classification(confidence: float, evidence: dict[str, Any] | None, has_trusted_title: bool = True) -> str:
        normalized_evidence = evidence or {}
        title_similarity = float(normalized_evidence.get("title_similarity", 0.0) or 0.0)
        title_verdict = ((normalized_evidence.get("field_evidence") or {}).get("title") or {}).get("verdict")
        if has_trusted_title:
            if title_verdict == "mismatch" or title_similarity < _TITLE_GATE_THRESHOLD:
                return "low_confidence"
            if confidence >= settings.external_academic_min_confidence and title_similarity >= _TITLE_STRONG_GATE_THRESHOLD:
                return "external_found"
            if confidence >= _POSSIBLE_MATCH_THRESHOLD:
                return "external_possible_match"
            return "low_confidence"
        else:
            if title_verdict == "mismatch":
                return "low_confidence"
            if confidence >= settings.external_academic_min_confidence:
                return "external_found"
            if confidence >= _POSSIBLE_MATCH_THRESHOLD:
                return "external_possible_match"
            return "low_confidence"

    @classmethod
    def _status_from_ranked_candidates(
        cls,
        ranked: list[tuple[CandidateWork, dict[str, Any]]],
        *,
        overall_degraded: bool,
        has_trusted_title: bool = True,
    ) -> str:
        if not ranked:
            return "source_degraded" if overall_degraded else "not_found"
        top_evidence = ranked[0][1]
        top_confidence = float(top_evidence.get("final_score", 0.0) or 0.0)
        top_status = cls._candidate_classification(top_confidence, top_evidence, has_trusted_title=has_trusted_title)
        if top_status in {"external_found", "external_possible_match"}:
            return top_status
        return "source_degraded" if overall_degraded else "low_confidence"

    @staticmethod
    def _confidence_label(confidence: float | None) -> str | None:
        if confidence is None:
            return None
        if confidence >= 0.90:
            return "High"
        if confidence >= 0.75:
            return "Medium"
        if confidence >= 0.60:
            return "Low"
        return None

    @staticmethod
    def _diagnostics_include_degradation(
        source_diagnostics: dict[str, Any],
        source_names: tuple[str, ...] | None = None,
    ) -> bool:
        names = source_names or tuple(source_diagnostics.keys())
        return any(
            isinstance(source_diagnostics.get(name), dict)
            and source_diagnostics.get(name, {}).get("state") in _DEGRADED_STATES
            for name in names
        )

    @staticmethod
    def _record_match_status(candidate_status: str, *, is_top: bool) -> str:
        if candidate_status == "external_found":
            return "best_match" if is_top else "candidate"
        if candidate_status == "external_possible_match":
            return "possible_match" if is_top else "candidate"
        return "low_confidence"

    @staticmethod
    def _should_query_pubmed(ref: ReferenceMetadata, preliminary: Any | None = None) -> bool:
        if ref.doi:
            return True
        if preliminary and getattr(preliminary, "best_candidate", None) is not None:
            best_candidate = preliminary.best_candidate
            if getattr(best_candidate, "doi", None) and float(getattr(preliminary, "confidence", 0.0) or 0.0) >= _POSSIBLE_MATCH_THRESHOLD:
                return True
        text = " ".join(
            part
            for part in [ref.title or "", " ".join(ref.authors or []), ref.venue or "", ref.raw or ""]
            if part
        )
        return bool(_PUBMED_HINT_RE.search(text))

    @staticmethod
    def _build_pubmed_query(ref: ReferenceMetadata, *, preferred_doi: str | None = None) -> str | None:
        doi = normalize_doi(preferred_doi or ref.doi or "")
        if doi:
            return f"{doi}[doi]"

        title_tokens = [token for token in normalize_title(ref.title or "").split() if len(token) >= 3]
        if not title_tokens:
            return None
        term = " ".join(title_tokens[:14])
        if ref.authors:
            family = ref.authors[0].split()[-1].strip(" ,.;:")
            if family:
                term = f"{term} AND {family}[Author]"
        return term

    @staticmethod
    def _normalize_pubmed_work(item: dict[str, Any] | None, pmid: str) -> CandidateWork | None:
        if not item:
            return None
        article_ids = item.get("articleids") or []
        doi = None
        pmcid = None
        for article_id in article_ids:
            if not isinstance(article_id, dict):
                continue
            idtype = str(article_id.get("idtype") or "").strip().lower()
            value = str(article_id.get("value") or "").strip()
            if not value:
                continue
            if idtype == "doi" and not doi:
                doi = normalize_doi(value)
            elif idtype in {"pmc", "pmcid"} and not pmcid:
                match = re.search(r"(PMC\d+)", value.upper())
                pmcid = match.group(1) if match else value

        title = str(item.get("title") or "").strip() or None
        authors = [
            str(author.get("name")).strip()
            for author in item.get("authors", []) or []
            if isinstance(author, dict) and str(author.get("name") or "").strip()
        ]
        year = None
        pubdate = str(item.get("pubdate") or "").strip()
        year_match = re.search(r"\b(19|20)\d{2}\b", pubdate)
        if year_match:
            year = int(year_match.group(0))
        volume = str(item.get("volume") or "").strip() or None
        issue = str(item.get("issue") or "").strip() or None
        pages = str(item.get("pages") or "").strip() or None
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None
        return CandidateWork(
            source="pubmed",
            title=title,
            authors=authors,
            year=year,
            venue=str(item.get("fulljournalname") or "").strip() or None,
            doi=doi,
            url=url,
            external_id=pmid,
            external_id_type="pmid",
            volume=volume,
            issue=issue,
            pages=pages,
            pmid=pmid,
            pmcid=pmcid,
            raw=item,
            resolved_url=url,
            evidence_urls=[url] if url else [],
        )

    @staticmethod
    def _query_terms_from_reference(ref: ReferenceMetadata) -> list[str]:
        parts: list[str] = []
        if ref.title:
            parts.extend(word for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]+", ref.title) if len(word) >= 4)
        if ref.authors:
            parts.extend(ref.authors[:2])
        deduped: list[str] = []
        seen: set[str] = set()
        for item in parts:
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:8]

    @staticmethod
    def _extract_strong_terms(text: str, extra_sources: list[str] | None = None) -> list[str]:
        combined = [text]
        if extra_sources:
            combined.extend(extra_sources)
        raw = " ".join(str(s) for s in combined if s)
        terms: list[str] = []
        for match in _STRONG_TERMS_RE.finditer(raw):
            term = match.group(0).strip()
            if len(term) >= 3 and not term.isdigit():
                terms.append(term)
        for match in _PRESERVED_ENTITY_RE.finditer(raw):
            term = match.group(0).strip()
            if term and term not in terms:
                terms.append(term)
        acronyms = re.findall(r"\b[A-Z]{2,}(?:-[A-Z]+)*\b", raw)
        for acro in acronyms:
            if acro not in terms and len(acro) >= 2:
                terms.append(acro)
        deduped: list[str] = []
        seen: set[str] = set()
        for term in terms:
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(term)
        return deduped[:12]

    @staticmethod
    def _normalize_internal_record(record: dict[str, Any], confidence: float) -> dict[str, Any]:
        return {
            "title": record.get("title"),
            "authors": list(record.get("authors") or []),
            "year": record.get("year"),
            "venue": record.get("venue"),
            "doi": record.get("doi"),
            "volume": record.get("volume"),
            "issue": record.get("issue"),
            "pages": record.get("pages"),
            "pmid": record.get("pmid"),
            "pmcid": record.get("pmcid"),
            "abstract": record.get("abstract"),
            "url": record.get("url"),
            "source": _SOURCE_LABELS["internal"],
            "confidence": round(confidence, 3),
            "match_status": "internal_match",
            "subjects": [],
            "keywords": [],
            "entity_type": record.get("entity_type"),
            "score": record.get("retrieval_score"),
        }

    def _record_from_exact_result(self, result: CitationCheckResult) -> dict[str, Any]:
        metadata = result.metadata or {}
        completed = result.completed_metadata or {}
        crossref = metadata.get("crossref") if isinstance(metadata.get("crossref"), dict) else {}
        openalex = metadata.get("openalex") if isinstance(metadata.get("openalex"), dict) else {}
        datacite = metadata.get("datacite") if isinstance(metadata.get("datacite"), dict) else {}
        subjects = self._extract_subjects_from_raw(result.source, crossref or openalex or datacite)
        keywords = self._extract_keywords_from_raw(result.source, openalex or datacite or crossref)
        abstract = self._extract_abstract_from_raw(result.source, crossref or openalex or datacite)
        identifier_type = str(result.matched_identifier_type or result.input_identifier_type or "").strip().lower()
        identifier_value = str(result.matched_identifier or result.input_identifier or "").strip()
        return {
            "title": result.matched_title or result.title,
            "authors": list(result.matched_authors or result.authors or []),
            "year": result.matched_year if result.matched_year is not None else result.year,
            "venue": result.matched_venue or self._extract_venue_from_raw(result.source, crossref or openalex or datacite),
            "doi": result.matched_doi or result.doi,
            "volume": completed.get("volume"),
            "issue": completed.get("issue"),
            "pages": completed.get("pages"),
            "pmid": identifier_value if identifier_type == "pmid" else completed.get("pmid"),
            "pmcid": identifier_value if identifier_type == "pmcid" else completed.get("pmcid"),
            "abstract": abstract,
            "url": result.resolved_url or completed.get("url"),
            "source": _SOURCE_LABELS.get(self._canonical_source_key(result.source), result.source or "Unknown"),
            "confidence": round(float(result.confidence or 1.0), 3),
            "match_status": result.metadata_consistency or "exact_match",
            "subjects": subjects,
            "keywords": keywords,
            "resolved_url": result.resolved_url,
            "evidence_urls": list(result.evidence_urls or []),
            "resolver_chain": list(result.resolver_chain or []),
            "matched_by": result.matched_by,
        }

    def _record_from_candidate(
        self,
        candidate: CandidateWork,
        *,
        confidence: float,
        match_status: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "title": candidate.title,
            "authors": list(candidate.authors or []),
            "year": candidate.year,
            "venue": candidate.venue,
            "doi": candidate.doi,
            "volume": candidate.volume,
            "issue": candidate.issue,
            "pages": candidate.pages,
            "pmid": candidate.pmid,
            "pmcid": candidate.pmcid,
            "abstract": self._extract_abstract_from_raw(candidate.source, candidate.raw),
            "url": candidate.resolved_url or candidate.url or (f"https://doi.org/{candidate.doi}" if candidate.doi else None),
            "source": _SOURCE_LABELS.get(self._canonical_source_key(candidate.source), candidate.source),
            "confidence": round(float(confidence or 0.0), 3),
            "match_status": match_status,
            "subjects": self._extract_subjects_from_raw(candidate.source, candidate.raw),
            "keywords": self._extract_keywords_from_raw(candidate.source, candidate.raw),
            "score": round(float(evidence.get("final_score", 0.0) or 0.0), 3),
            "resolved_url": candidate.resolved_url or candidate.url,
            "evidence_urls": list(candidate.evidence_urls or []),
        }

    @staticmethod
    def _extract_abstract_from_raw(source: str | None, raw: dict[str, Any] | None) -> str | None:
        payload = raw or {}
        abstract = payload.get("abstract")
        if isinstance(abstract, str) and abstract.strip():
            return re.sub(r"<[^>]+>", " ", abstract).replace("\n", " ").strip()

        if source and "openalex" in source.lower():
            inverted = payload.get("abstract_inverted_index")
            if not isinstance(inverted, dict) or not inverted:
                return None
            size = 0
            for positions in inverted.values():
                if isinstance(positions, list):
                    for pos in positions:
                        if isinstance(pos, int):
                            size = max(size, pos + 1)
            if size <= 0:
                return None
            tokens = [""] * size
            for word, positions in inverted.items():
                if not isinstance(word, str) or not isinstance(positions, list):
                    continue
                for pos in positions:
                    if isinstance(pos, int) and 0 <= pos < size:
                        tokens[pos] = word
            text = " ".join(token for token in tokens if token).strip()
            return text or None
        return None

    @staticmethod
    def _extract_subjects_from_raw(source: str | None, raw: dict[str, Any] | None) -> list[str]:
        payload = raw or {}
        subjects: list[str] = []
        if isinstance(payload.get("subject"), list):
            subjects.extend(str(item).strip() for item in payload.get("subject", []) if str(item).strip())
        for concept in payload.get("concepts", []) or []:
            if isinstance(concept, dict) and concept.get("display_name"):
                subjects.append(str(concept["display_name"]).strip())
        for field in payload.get("fieldsOfStudy", []) or []:
            if isinstance(field, str) and field.strip():
                subjects.append(field.strip())
            elif isinstance(field, dict) and field.get("name"):
                subjects.append(str(field["name"]).strip())
        return ExternalAcademicSearchService._dedupe_strings(subjects)

    @staticmethod
    def _extract_keywords_from_raw(source: str | None, raw: dict[str, Any] | None) -> list[str]:
        payload = raw or {}
        keywords: list[str] = []
        for item in payload.get("keywords", []) or []:
            if isinstance(item, dict):
                value = item.get("display_name") or item.get("keyword")
                if value:
                    keywords.append(str(value).strip())
            elif isinstance(item, str) and item.strip():
                keywords.append(item.strip())
        return ExternalAcademicSearchService._dedupe_strings(keywords)

    @staticmethod
    def _extract_venue_from_raw(source: str | None, raw: dict[str, Any] | None) -> str | None:
        payload = raw or {}
        containers = payload.get("container-title")
        if isinstance(containers, list) and containers:
            return str(containers[0]).strip() or None
        if isinstance(containers, str) and containers.strip():
            return containers.strip()

        primary_location = payload.get("primary_location")
        if isinstance(primary_location, dict):
            source_info = primary_location.get("source") or {}
            if isinstance(source_info, dict) and source_info.get("display_name"):
                return str(source_info["display_name"]).strip()
        host_venue = payload.get("host_venue")
        if isinstance(host_venue, dict) and host_venue.get("display_name"):
            return str(host_venue["display_name"]).strip()
        if isinstance(payload.get("venue"), str) and payload.get("venue", "").strip():
            return str(payload["venue"]).strip()
        return None

    @staticmethod
    def _dedupe_strings(values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped[:8]

    @staticmethod
    def _canonical_source_key(source: str | None) -> str:
        normalized = (source or "").strip().lower()
        if "crossref" in normalized:
            return "crossref"
        if "openalex" in normalized or normalized == "pyalex":
            return "openalex"
        if "pubmed" in normalized:
            return "pubmed"
        if "semantic" in normalized:
            return "semantic_scholar"
        if "datacite" in normalized:
            return "datacite"
        if "publisher" in normalized:
            return "publisher_meta"
        return normalized

    def _internal_checked_source(self, result: AcademicQueryResult) -> dict[str, Any]:
        if not result.query_terms:
            return self._checked_source("internal", "skipped", detail="No internal search terms could be extracted.", candidate_count=0)
        if academic_query_service.has_sufficient_confidence(result):
            detail = f"Found {len(result.records)} grounded internal records."
            return self._checked_source("internal", "matched", detail=detail, candidate_count=len(result.records))
        if result.records:
            detail = f"Found {len(result.records)} internal candidates, but confidence stayed below the fallback threshold."
            return self._checked_source("internal", "low_confidence", detail=detail, candidate_count=len(result.records))
        detail = f"Checked internal terms: {', '.join(result.query_terms[:6])}."
        return self._checked_source("internal", "no_match", detail=detail, candidate_count=0)

    @staticmethod
    def _checked_source(source_key: str, state: str, *, detail: str | None = None, candidate_count: int = 0) -> dict[str, Any]:
        return {
            "name": _SOURCE_LABELS.get(source_key, source_key),
            "state": state,
            "detail": detail,
            "candidate_count": candidate_count,
        }

    def _diagnostic_to_checked_source(self, source_key: str, diagnostic: dict[str, Any]) -> dict[str, Any]:
        return self._checked_source(
            source_key,
            str(diagnostic.get("state") or "unknown"),
            detail=str(diagnostic.get("detail")) if diagnostic.get("detail") else None,
            candidate_count=int(diagnostic.get("candidate_count", 0) or 0),
        )

    def _checked_sources_from_diagnostics(self, diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
        ordered = []
        for key in ("crossref", "pubmed", "datacite", "openalex", "semantic_scholar", "publisher_meta", "web_search"):
            diagnostic = diagnostics.get(key)
            if isinstance(diagnostic, dict):
                ordered.append(self._diagnostic_to_checked_source(key, diagnostic))
        return ordered

    @staticmethod
    def _cache_key(text: str, ref: ReferenceMetadata) -> str:
        doi = next(iter(citation_checker.extract_dois(text)), None)
        if doi:
            return f"doi:{normalize_doi(doi)}"
        exact_identifiers = citation_checker.extract_exact_identifiers(text)
        if exact_identifiers:
            first = exact_identifiers[0]
            return f"id:{first.get('identifier_type')}:{str(first.get('identifier') or '').lower()}"
        normalized_title = normalize_title(ref.title or text)
        normalized_authors = "|".join(normalize_author_name(author) for author in ref.authors[:3])
        return f"query:{normalized_title}:{normalized_authors}:{ref.year or ''}:{normalize_venue(ref.venue or '')}"

    def _get_cached(self, key: str) -> ScholarlyLookupResult | None:
        if not key:
            return None
        cached = self._cache.get(key)
        if cached is None:
            return None
        expires_at, result = cached
        if expires_at < time.time():
            self._cache.pop(key, None)
            return None
        return copy.deepcopy(result)

    def _set_cached(self, key: str, result: ScholarlyLookupResult) -> None:
        if not key or settings.external_academic_cache_ttl_seconds <= 0:
            return
        self._cache[key] = (time.time() + settings.external_academic_cache_ttl_seconds, copy.deepcopy(result))


external_academic_search_service = ExternalAcademicSearchService()
