from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CitationCheckResult:
    """Structured citation verification result."""

    citation: str
    status: str
    evidence: str | None = None
    doi: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    source: str | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    verification_mode: str | None = None
    input_doi: str | None = None
    matched_doi: str | None = None
    input_identifier: str | None = None
    input_identifier_type: str | None = None
    matched_identifier: str | None = None
    matched_identifier_type: str | None = None
    matched_title: str | None = None
    matched_year: int | None = None
    matched_authors: list[str] = field(default_factory=list)
    matched_venue: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    warning: str | None = None
    evidence_breakdown: dict[str, float] | None = None
    reason: str | None = None
    field_evidence: dict[str, Any] | None = None
    source_diagnostics: dict[str, Any] = field(default_factory=dict)
    parse_status: str | None = None
    search_attempted: bool = False
    search_strategy: str | None = None
    metadata_consistency: str | None = None
    completed_metadata: dict[str, Any] | None = None
    formatted_apa: str | None = None
    formatted_bibtex: str | None = None
    csl_json: dict[str, Any] | None = None
    resolved_url: str | None = None
    evidence_urls: list[str] = field(default_factory=list)
    resolver_chain: list[str] = field(default_factory=list)
    candidate_gap: float | None = None
    matched_by: str | None = None
    discovered_from: str | None = None
    source_domain: str | None = None
    web_search_query: str | None = None
    web_search_provider: str | None = None
    web_search_skipped_reason: str | None = None


@dataclass
class ReferenceMetadata:
    raw: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    confidence: float = 0.0


@dataclass
class CandidateWork:
    source: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    external_id: str | None = None
    external_id_type: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    resolved_url: str | None = None
    evidence_urls: list[str] = field(default_factory=list)
    source_domain: str | None = None


@dataclass
class MetadataMatchResult:
    reference: ReferenceMetadata
    status: str
    confidence: float
    best_candidate: CandidateWork | None = None
    candidates: list[CandidateWork] = field(default_factory=list)
    candidate_details: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    warning: str | None = None
    reason: str | None = None
    field_evidence: dict[str, Any] | None = None
    source_diagnostics: dict[str, Any] = field(default_factory=dict)
    parse_status: str | None = None
    search_attempted: bool = False
    search_strategy: str | None = None
    candidate_gap: float | None = None
    matched_by: str | None = None
    resolved_url: str | None = None
    evidence_urls: list[str] = field(default_factory=list)
    resolver_chain: list[str] = field(default_factory=list)
    discovered_from: str | None = None
    source_domain: str | None = None
    web_search_query: str | None = None
    web_search_provider: str | None = None
    web_search_skipped_reason: str | None = None
