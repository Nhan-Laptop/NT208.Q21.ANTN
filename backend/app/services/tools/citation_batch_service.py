from __future__ import annotations

import copy
import json
import logging
import re
import unicodedata
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from app.services.academic_verification_formatter import format_citation_summary
from app.services.tools.citation.models import CandidateWork
from app.services.tools.citation.parser import (
    build_fallback_title_query,
    extract_first_url,
    extract_reference_items,
    is_reference_preamble_line,
    parse_reference_metadata,
)
from app.services.tools.citation.sources.publisher_meta import PublisherMetaSource
from app.services.tools.citation_checker import CitationCheckResult, citation_checker

logger = logging.getLogger(__name__)

_PUBLISHER_META_SOURCE = PublisherMetaSource()

VERIFIED_CITATION_STATUSES = frozenset({
    "DOI_VERIFIED",
    "IDENTIFIER_VERIFIED",
    "METADATA_VERIFIED",
})
REVIEW_CITATION_STATUSES = frozenset({
    "LIKELY_MATCH",
    "POSSIBLE_MATCH",
    "AMBIGUOUS_MATCH",
    "UNVERIFIED_NO_DOI",
})
PROBLEM_CITATION_STATUSES = frozenset({
    "DOI_NOT_FOUND",
    "IDENTIFIER_NOT_FOUND",
    "NO_MATCH_FOUND",
    "PARSE_FAILED",
})
TEMPORARY_ISSUE_CITATION_STATUSES = frozenset({"UNVERIFIED"})
_SOURCE_TYPE_SCHOLARLY_IDENTIFIER = "scholarly_identifier"
_SOURCE_TYPE_SCHOLARLY_REFERENCE = "scholarly_reference"
_SOURCE_TYPE_WEB_URL = "web_url"
_SOURCE_TYPE_BLOG_OR_NON_SCHOLARLY = "blog_or_non_scholarly"
_SOURCE_TYPE_INSUFFICIENT_DESCRIPTION = "insufficient_description"
_WEB_SIGNAL_RE = re.compile(
    r"\b("
    r"blog|personal\s+blog|website|web\s?page|webpage|available\s+from|retrieved\s+from|"
    r"accessed|cited|blog\s+ca\s+nhan|bai\s+blog|trang\s+web|nguon\s+web|"
    r"truy\s+cap\s+ngay|lay\s+tu|co\s+tai"
    r")\b",
    re.IGNORECASE,
)
_REFERENCE_REQUEST_PATTERNS = (
    re.compile(r"^(?:please\s+)?(?:check|verify|review|scan|inspect|analy[sz]e|look\s+up)\b"),
    re.compile(r"^(?:kiem\s+tra|xac\s+minh|ra\s+soat|doi\s+chieu|xem\s+giup)\b"),
)
_REFERENCE_HEADING_PATTERNS = (
    re.compile(r"^(?:references?|bibliography|citations?|citation\s+list)\s*$"),
    re.compile(r"^(?:(?:these|the\s+following)\s+)?(?:citations?|references?)\s*$"),
    re.compile(
        r"^(?:cac\s+bai|cac\s+muc|cac\s+trich\s+dan|tai\s+lieu\s+tham\s+khao)"
        r"(?:\s+(?:sau|can\s+kiem\s+tra))?\s*$"
    ),
)


def is_verified_citation_status(status: str | None) -> bool:
    normalized = str(status or "").strip().upper()
    return normalized in VERIFIED_CITATION_STATUSES


class CitationBatchService:
    """Batch/report orchestration over the existing citation checker core.

    This layer is intentionally presentation-oriented: it extracts multiple
    occurrences from one pasted bibliography, preserves every occurrence in the
    original order, reuses request-local caching without collapsing duplicate
    rows, and builds a report payload for chat/UI rendering.

    Verification semantics stay inside ``citation_checker``:
    - DOI input: exact DOI resolution only, no fuzzy promotion on failure.
    - PMID / PMCID / OpenAlex ID: exact identifier resolution only.
    - Metadata path: scholarly-source fallback chain stays
      Crossref -> OpenAlex -> DataCite (when needed) -> Semantic Scholar
      (when enabled and evidence is weak/incomplete) -> web discovery fallback.
      If web discovery finds a DOI, the DOI is re-verified through exact DOI
      lookup before promotion.
    - AI-generated summary text may explain existing evidence but must never
      override technical statuses.
    """

    def verify_text(
        self,
        text: str,
        *,
        include_ai_summary: bool = False,
        max_items: int | None = None,
    ) -> dict[str, Any]:
        normalized_text = citation_checker._normalize_input_text(text or "")
        occurrences = self._extract_occurrences(normalized_text)
        if max_items is not None and max_items >= 0:
            occurrences = occurrences[:max_items]

        if not occurrences:
            statistics = citation_checker.get_statistics([])
            summary_text = format_citation_summary(
                statistics,
                no_citation_found=True,
                results=[],
            )
            summary = self._build_summary([], summary_text=summary_text, ai_summary_text=None)
            return {
                "type": "citation_report",
                "data": [],
                "results": [],
                "summary": summary,
                "statistics": statistics,
                "no_citation_found": True,
                "text": summary_text,
            }

        cache: dict[tuple[str, str], CitationCheckResult] = {}
        raw_results: list[CitationCheckResult] = []
        results: list[dict[str, Any]] = []

        for index, occurrence in enumerate(occurrences, start=1):
            try:
                raw_result = self._verify_occurrence(occurrence, cache)
            except Exception as exc:
                logger.exception("Batch citation occurrence failed: %s", occurrence.get("raw"))
                raw_result = self._build_unexpected_error_result(occurrence, exc)
            raw_results.append(raw_result)
            results.append(self._build_result_item(raw_result, occurrence=occurrence, index=index))

        statistics = citation_checker.get_statistics(raw_results)
        summary_text = format_citation_summary(
            statistics,
            no_citation_found=bool(statistics.get("no_citation_found", False)),
            results=raw_results,
        )
        ai_summary_text = None
        if include_ai_summary:
            try:
                ai_summary_text = self._maybe_generate_ai_summary(results)
            except Exception:
                logger.exception("Batch citation AI summary generation failed unexpectedly.")
        summary = self._build_summary(
            results,
            summary_text=summary_text,
            ai_summary_text=ai_summary_text,
        )

        return {
            "type": "citation_report",
            "data": results,
            "results": results,
            "summary": summary,
            "statistics": statistics,
            "no_citation_found": False,
            "text": summary_text,
        }

    def _extract_occurrences(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []

        occurrences: list[dict[str, Any]] = []
        for item in extract_reference_items(text):
            occurrence = self._build_occurrence_from_item(item)
            if occurrence is not None:
                occurrences.append(occurrence)

        if occurrences:
            return occurrences

        return [dict(item) for item in citation_checker.extract_citations(text)]

    @staticmethod
    def _normalize_candidate_text(text: str) -> str:
        cleaned = citation_checker._normalize_input_text(text or "")
        cleaned = re.sub(r"^\s*(?:[-*•]|\[\d+\]|\d+[.)])\s*", "", cleaned).strip()
        return cleaned

    @staticmethod
    def _ascii_fold_text(text: str) -> str:
        folded = unicodedata.normalize("NFKD", text or "")
        ascii_text = folded.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", ascii_text).strip().lower()

    @classmethod
    def _looks_like_reference_preamble(cls, text: str) -> bool:
        return is_reference_preamble_line(text)

    @classmethod
    def _should_keep_raw_reference(cls, text: str) -> bool:
        cleaned = cls._normalize_candidate_text(text)
        if not cleaned or cls._looks_like_reference_preamble(cleaned):
            return False

        parsed = parse_reference_metadata(cleaned)
        has_structured_metadata = bool(
            parsed.authors
            or parsed.year is not None
            or parsed.venue
            or parsed.volume
            or parsed.issue
            or parsed.pages
        )
        if has_structured_metadata:
            return True

        return bool(build_fallback_title_query(cleaned, parsed))

    @classmethod
    def _looks_like_scholarly_reference(cls, raw: str, parsed) -> bool:
        if parsed.authors and parsed.year is not None and (
            parsed.venue or parsed.volume or parsed.issue or parsed.pages
        ):
            return True
        if parsed.title and parsed.year is not None and (
            parsed.venue or parsed.volume or parsed.issue or parsed.pages
        ):
            return True
        fallback = build_fallback_title_query(raw, parsed)
        return bool(fallback and parsed.authors and parsed.year is not None)

    @classmethod
    def _has_web_reference_signals(cls, raw: str, url: str | None) -> bool:
        if url:
            return True
        return bool(_WEB_SIGNAL_RE.search(cls._ascii_fold_text(raw)))

    @classmethod
    def _has_web_keyword_signals(cls, raw: str) -> bool:
        return bool(_WEB_SIGNAL_RE.search(cls._ascii_fold_text(raw)))

    @staticmethod
    def _is_doi_host(url: str | None) -> bool:
        if not url:
            return False
        try:
            hostname = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
        except ValueError:
            return False
        return hostname in {"doi.org", "dx.doi.org", "www.doi.org"}

    @classmethod
    def _classify_source_type(
        cls,
        *,
        raw: str,
        parsed,
        doi: str | None,
        exact_identifiers: list[dict[str, str]],
        url: str | None,
    ) -> str:
        if doi or exact_identifiers:
            return _SOURCE_TYPE_SCHOLARLY_IDENTIFIER

        scholarly_reference = cls._looks_like_scholarly_reference(raw, parsed)
        web_signals = cls._has_web_reference_signals(raw, url)
        web_keyword_signals = cls._has_web_keyword_signals(raw)
        if url and scholarly_reference and not web_keyword_signals:
            return _SOURCE_TYPE_SCHOLARLY_REFERENCE
        if url:
            return _SOURCE_TYPE_WEB_URL
        if scholarly_reference:
            return _SOURCE_TYPE_SCHOLARLY_REFERENCE
        if web_signals:
            return _SOURCE_TYPE_BLOG_OR_NON_SCHOLARLY
        return _SOURCE_TYPE_INSUFFICIENT_DESCRIPTION

    @classmethod
    def _should_keep_single_reference(
        cls,
        *,
        raw: str,
        parsed,
        doi: str | None,
        exact_identifiers: list[dict[str, str]],
        url: str | None,
        source_type: str,
    ) -> bool:
        normalized = cls._ascii_fold_text(raw)
        if any(pattern.match(normalized) for pattern in _REFERENCE_REQUEST_PATTERNS):
            return False
        if doi or exact_identifiers or url:
            return True
        if source_type in {
            _SOURCE_TYPE_SCHOLARLY_REFERENCE,
            _SOURCE_TYPE_BLOG_OR_NON_SCHOLARLY,
        }:
            return True
        return False

    def _build_occurrence_from_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        raw = str(item.get("raw") or "").strip()
        if not raw or self._looks_like_reference_preamble(raw):
            return None

        explicit_marker = bool(item.get("explicit_marker"))
        source_number = item.get("source_number")
        doi = next(iter(citation_checker.extract_dois(raw)), None)
        exact_identifiers = citation_checker.extract_exact_identifiers(raw)
        url = extract_first_url(raw)
        if url and self._is_doi_host(url) and doi:
            url = None
        parsed = parse_reference_metadata(raw)
        source_type = self._classify_source_type(
            raw=raw,
            parsed=parsed,
            doi=doi,
            exact_identifiers=exact_identifiers,
            url=url,
        )
        if not explicit_marker and not self._should_keep_single_reference(
            raw=raw,
            parsed=parsed,
            doi=doi,
            exact_identifiers=exact_identifiers,
            url=url,
            source_type=source_type,
        ):
            return None

        occurrence: dict[str, Any] = {
            "raw": raw,
            "context_block": raw,
            "type": "raw_reference",
            "authors": list(parsed.authors or []) or None,
            "year": parsed.year,
            "doi": None,
            "source_type": source_type,
            "source_number": source_number,
            "url": url,
        }
        if doi:
            occurrence["type"] = "doi"
            occurrence["doi"] = doi
            occurrence["exact_raw"] = doi
            return occurrence

        if exact_identifiers:
            identifier = exact_identifiers[0]
            occurrence["type"] = identifier["identifier_type"]
            occurrence["identifier"] = identifier["identifier"]
            occurrence["identifier_type"] = identifier["identifier_type"]
            occurrence["exact_raw"] = identifier["raw"]
            return occurrence

        if source_type == _SOURCE_TYPE_WEB_URL:
            occurrence["type"] = "web_url"
            return occurrence
        if source_type == _SOURCE_TYPE_BLOG_OR_NON_SCHOLARLY:
            occurrence["type"] = "blog_or_non_scholarly"
            return occurrence
        if source_type == _SOURCE_TYPE_INSUFFICIENT_DESCRIPTION:
            occurrence["type"] = "insufficient_description"
            return occurrence

        return occurrence

    def _verify_occurrence(
        self,
        occurrence: dict[str, Any],
        cache: dict[tuple[str, str], CitationCheckResult],
    ) -> CitationCheckResult:
        cache_key = self._cache_key_for_occurrence(occurrence)
        cached = cache.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)

        occurrence_type = str(occurrence.get("type") or "").lower()
        if occurrence_type == "doi":
            raw_doi = str(occurrence.get("doi") or occurrence.get("exact_raw") or occurrence.get("raw") or "")
            result = citation_checker.verify_doi_exact(raw_doi, citation_context=occurrence)
            normalized_doi = citation_checker.normalize_doi(raw_doi)
            result.verification_mode = "doi"
            result.input_doi = normalized_doi or None
            if result.status == "DOI_VERIFIED":
                result.matched_doi = result.doi
                result.matched_title = result.title
                result.matched_year = result.year
                result.matched_authors = list(result.authors or [])
        elif occurrence_type in {"pmid", "pmcid", "openalex"}:
            identifier_value = str(
                occurrence.get("identifier") or occurrence.get("exact_raw") or occurrence.get("raw") or ""
            )
            result = citation_checker.verify_identifier_exact(
                identifier_value,
                occurrence_type,
                citation_context=occurrence,
            )
        elif occurrence_type == "web_url":
            result = self._verify_web_source_occurrence(occurrence)
        elif occurrence_type == "blog_or_non_scholarly":
            result = self._build_non_scholarly_review_result(occurrence)
        elif occurrence_type == "insufficient_description":
            result = self._build_insufficient_description_result(occurrence)
        else:
            result = citation_checker._verify_metadata_match(occurrence)

        cache[cache_key] = copy.deepcopy(result)
        return result

    @staticmethod
    def _cache_key_for_occurrence(occurrence: dict[str, Any]) -> tuple[str, str]:
        occurrence_type = str(occurrence.get("type") or "").lower()
        if occurrence_type == "doi":
            doi = citation_checker.normalize_doi(str(occurrence.get("doi") or occurrence.get("raw") or ""))
            return ("doi", doi)

        if occurrence_type in {"pmid", "pmcid", "openalex"}:
            identifier = citation_checker.normalize_exact_identifier(
                str(occurrence.get("identifier") or occurrence.get("raw") or ""),
                occurrence_type,
            ) or str(occurrence.get("identifier") or occurrence.get("raw") or "").strip()
            return (occurrence_type, identifier.lower())
        if occurrence_type == "web_url":
            url = str(occurrence.get("url") or occurrence.get("raw") or "").strip().lower()
            return ("web_url", url)

        raw = citation_checker._normalize_input_text(str(occurrence.get("raw") or "")).strip().lower()
        return ("metadata", raw)

    def _build_result_item(
        self,
        result: CitationCheckResult,
        *,
        occurrence: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        payload = copy.deepcopy(vars(result))
        status = str(payload.get("status") or "").upper()
        raw_citation = str(occurrence.get("raw") or payload.get("citation") or "").strip()

        if not is_verified_citation_status(status):
            payload["completed_metadata"] = None
            payload["formatted_apa"] = None
            payload["formatted_bibtex"] = None
            payload["csl_json"] = None

        payload.update(
            {
                "index": index,
                "raw_citation": raw_citation,
                "source_type": occurrence.get("source_type"),
                "source_number": occurrence.get("source_number"),
                "ux_group": self._ux_group_for_status(status),
                "short_issue": self._short_issue_for_result(status, payload),
                "suggested_action": self._suggested_action_for_status(status, payload),
            }
        )
        return payload

    @staticmethod
    def _diagnostic(state: str, detail: str | None = None, candidate_count: int | None = None) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {"state": state}
        if detail:
            diagnostic["detail"] = detail
        if candidate_count is not None:
            diagnostic["candidate_count"] = candidate_count
        return diagnostic

    @staticmethod
    def _source_domain_for_url(url: str | None) -> str | None:
        if not url:
            return None
        try:
            hostname = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
        except ValueError:
            return None
        return hostname or None

    def _verify_web_source_occurrence(self, occurrence: dict[str, Any]) -> CitationCheckResult:
        raw = str(occurrence.get("raw") or "")
        url = str(occurrence.get("url") or "").strip()
        source_domain = self._source_domain_for_url(url)
        if not url:
            return self._build_insufficient_description_result(occurrence)

        candidate = CandidateWork(
            source="web_url",
            url=url,
            resolved_url=url,
            source_domain=source_domain,
            evidence_urls=[url],
        )
        try:
            enriched = _PUBLISHER_META_SOURCE.enrich_candidate(candidate)
        except Exception as exc:
            logger.debug("Web metadata lookup failed for %s: %s", url, exc)
            return CitationCheckResult(
                citation=raw,
                status="UNVERIFIED",
                source="web_url",
                confidence=0.0,
                verification_mode="web_source",
                warning="Unable to fetch reliable metadata for this web source right now.",
                reason="The input looks like a web source, but its page metadata could not be retrieved reliably.",
                source_diagnostics={"publisher_meta": self._diagnostic("error", str(exc), 0)},
                parse_status="NOT_PROVIDED",
                search_attempted=True,
                search_strategy="direct_url_metadata",
                resolved_url=url,
                evidence_urls=[url],
                resolver_chain=["publisher_meta"],
                source_domain=source_domain,
            )

        title = enriched.title or None
        year = enriched.year
        venue = enriched.venue or source_domain
        evidence_urls = list(dict.fromkeys([*(enriched.evidence_urls or []), url]))
        return CitationCheckResult(
            citation=raw,
            status="UNVERIFIED_NO_DOI",
            title=title,
            year=year,
            source="web_url",
            confidence=0.35 if title else 0.15,
            verification_mode="web_source",
            matched_title=title,
            matched_year=year,
            matched_venue=venue,
            warning="Web source metadata extracted; manual review is still required.",
            reason=(
                "This input appears to be a web source rather than a scholarly record. "
                "Review the page title, organization/author, publication date, and accessed date manually before citing."
            ),
            source_diagnostics={"publisher_meta": self._diagnostic("matched", None, 1)},
            parse_status="NOT_PROVIDED",
            search_attempted=True,
            search_strategy="direct_url_metadata",
            resolved_url=enriched.resolved_url or url,
            evidence_urls=evidence_urls,
            resolver_chain=["publisher_meta"],
            source_domain=source_domain,
        )

    def _build_non_scholarly_review_result(self, occurrence: dict[str, Any]) -> CitationCheckResult:
        raw = str(occurrence.get("raw") or "")
        return CitationCheckResult(
            citation=raw,
            status="UNVERIFIED_NO_DOI",
            source="non_scholarly",
            confidence=0.1,
            verification_mode="non_scholarly",
            warning="Non-scholarly source metadata is incomplete.",
            reason=(
                "This input appears to describe a blog or general web source, but it does not provide enough "
                "metadata to verify safely. Add a direct URL plus title, author/organization, and publication date."
            ),
            source_diagnostics={"web_source": self._diagnostic("skipped", "No direct URL was available for metadata lookup.", 0)},
            parse_status="NOT_PROVIDED",
            search_attempted=False,
            search_strategy=None,
        )

    def _build_insufficient_description_result(self, occurrence: dict[str, Any]) -> CitationCheckResult:
        raw = str(occurrence.get("raw") or "")
        return CitationCheckResult(
            citation=raw,
            status="UNVERIFIED_NO_DOI",
            source="insufficient_description",
            confidence=0.0,
            verification_mode="none",
            warning="Need fuller citation details before verification can continue.",
            reason="Provide a fuller reference line, DOI, exact identifier, or direct URL for this item.",
            source_diagnostics={"batch_parser": self._diagnostic("skipped", "The item did not contain enough verifiable source metadata.", 0)},
            parse_status="UNPARSABLE",
            search_attempted=False,
            search_strategy=None,
        )

    def _build_unexpected_error_result(
        self,
        occurrence: dict[str, Any],
        exc: Exception,
    ) -> CitationCheckResult:
        raw = str(occurrence.get("raw") or "")
        return CitationCheckResult(
            citation=raw,
            status="UNVERIFIED",
            source="batch_pipeline",
            confidence=0.0,
            verification_mode="none",
            warning="Verification for this item stopped because of a temporary processing issue.",
            reason="This row could not be completed due to an internal processing error. Retry later or review it manually.",
            source_diagnostics={"batch_pipeline": self._diagnostic("error", str(exc), 0)},
            parse_status="ERROR",
            search_attempted=False,
            search_strategy=None,
        )

    @staticmethod
    def _ux_group_for_status(status: str) -> str:
        if is_verified_citation_status(status):
            return "verified"
        if status in REVIEW_CITATION_STATUSES:
            return "review"
        if status in PROBLEM_CITATION_STATUSES:
            return "problem"
        if status in TEMPORARY_ISSUE_CITATION_STATUSES:
            return "temporary_issue"
        return "problem"

    @staticmethod
    def _short_issue_for_result(status: str, payload: dict[str, Any]) -> str | None:
        warning = str(payload.get("warning") or "").strip()
        if warning:
            return warning

        issues = {
            "DOI_VERIFIED": None,
            "IDENTIFIER_VERIFIED": None,
            "METADATA_VERIFIED": None,
            "LIKELY_MATCH": "Strong candidate found, but evidence is not strong enough for verified status.",
            "POSSIBLE_MATCH": "Only a low-confidence candidate was found.",
            "AMBIGUOUS_MATCH": "Multiple candidates look similarly plausible.",
            "UNVERIFIED_NO_DOI": "Candidate evidence is too weak without a resolving DOI or stronger metadata.",
            "DOI_NOT_FOUND": "The supplied DOI did not resolve exactly.",
            "IDENTIFIER_NOT_FOUND": "The supplied exact identifier did not resolve exactly.",
            "NO_MATCH_FOUND": "No scholarly source returned a plausible metadata match.",
            "PARSE_FAILED": "The reference is too short or incomplete to parse reliably.",
            "UNVERIFIED": "Verification could not be completed because scholarly sources were temporarily degraded.",
        }
        return issues.get(status)

    @staticmethod
    def _suggested_action_for_status(status: str, payload: dict[str, Any]) -> str | None:
        source_type = str(payload.get("source_type") or "").strip().lower()
        if source_type == _SOURCE_TYPE_WEB_URL:
            return "Review the linked page manually and capture title, organization/author, publication date, and accessed date."
        if source_type == _SOURCE_TYPE_BLOG_OR_NON_SCHOLARLY:
            return "Add the direct URL plus title, author/organization, and publication date for this web or blog source."
        if source_type == _SOURCE_TYPE_INSUFFICIENT_DESCRIPTION:
            return "Provide a fuller reference line, DOI, exact identifier, or direct URL."

        actions = {
            "DOI_VERIFIED": "Keep the exact DOI or publisher URL in the final reference list.",
            "IDENTIFIER_VERIFIED": "Keep the exact identifier and cross-check the displayed metadata before citing.",
            "METADATA_VERIFIED": "Use the verified metadata when preparing the final reference.",
            "LIKELY_MATCH": "Review title, authors, year, and DOI manually before using this citation.",
            "POSSIBLE_MATCH": "Check the candidate record manually and add a DOI or fuller reference if available.",
            "AMBIGUOUS_MATCH": "Open the candidate records and select the correct work manually.",
            "UNVERIFIED_NO_DOI": "Provide a fuller reference line or DOI to improve verification.",
            "DOI_NOT_FOUND": "Recheck the DOI at doi.org or on the publisher page.",
            "IDENTIFIER_NOT_FOUND": "Recheck the PMID, PMCID, or OpenAlex ID before citing.",
            "NO_MATCH_FOUND": "Check the title, authors, venue, and year, then retry with a fuller reference.",
            "PARSE_FAILED": "Provide a full reference line instead of a short inline citation.",
            "UNVERIFIED": "Retry later when scholarly sources are available again.",
        }
        return actions.get(status)

    def _build_summary(
        self,
        results: list[dict[str, Any]],
        *,
        summary_text: str,
        ai_summary_text: str | None,
    ) -> dict[str, Any]:
        status_counts = Counter(str(item.get("status") or "UNVERIFIED") for item in results)
        group_counts = Counter(str(item.get("ux_group") or "problem") for item in results)
        return {
            "total_count": len(results),
            "verified_count": int(group_counts.get("verified", 0)),
            "review_count": int(group_counts.get("review", 0)),
            "problem_count": int(group_counts.get("problem", 0)),
            "temporary_issue_count": int(group_counts.get("temporary_issue", 0)),
            "status_counts": dict(sorted(status_counts.items())),
            "summary_text": ai_summary_text,
            "default_summary_text": summary_text,
        }

    def _maybe_generate_ai_summary(self, results: list[dict[str, Any]]) -> str | None:
        compact_results = [
            {
                "index": item.get("index"),
                "status": item.get("status"),
                "ux_group": item.get("ux_group"),
                "matched_title": item.get("matched_title"),
                "matched_doi": item.get("matched_doi"),
                "short_issue": item.get("short_issue"),
                "suggested_action": item.get("suggested_action"),
            }
            for item in results
            if str(item.get("ux_group") or "") != "verified"
        ][:12]

        payload = {
            "counts": self._build_summary(results, summary_text="", ai_summary_text=None),
            "results": compact_results,
        }

        try:
            from app.services.llm_service import gemini_service
        except Exception:
            logger.debug("AI summary skipped because llm_service is unavailable.", exc_info=True)
            return None

        if not getattr(gemini_service, "enabled", False):
            return None

        system_instruction = (
            "You summarize citation verification reports in Vietnamese. "
            "Do not change any technical status. "
            "Do not claim a citation is verified unless the provided status already says so. "
            "Return 2-4 short sentences covering overall status, common issues, and next actions."
        )
        prompt = (
            "Summarize this batch citation review report for a human reviewer. "
            "Use only the structured evidence below.\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

        try:
            generated = gemini_service.generate_simple(prompt, system_instruction)
        except Exception:
            logger.exception("Batch citation AI summary generation failed.")
            return None
        return generated.strip() if generated else None


citation_batch_service = CitationBatchService()
