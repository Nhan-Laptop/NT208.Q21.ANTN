from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VerifyCitationRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=5)


class CitationBatchVerifyRequest(BaseModel):
    session_id: str | None = None
    text: str = Field(min_length=5)
    include_ai_summary: bool = False
    max_items: int | None = Field(default=None, ge=1)


class CitationItem(BaseModel):
    citation: str
    status: str
    evidence: str | None = None
    doi: str | None = None
    title: str | None = None
    authors: list[str] = []
    year: int | None = None
    source: str | None = None
    confidence: float = 0.0
    # No-DOI metadata-matching fields (all optional; backward compatible).
    verification_mode: str | None = None
    input_doi: str | None = None
    matched_doi: str | None = None
    input_identifier: str | None = None
    input_identifier_type: str | None = None
    matched_identifier: str | None = None
    matched_identifier_type: str | None = None
    matched_title: str | None = None
    matched_year: int | None = None
    matched_authors: list[str] = []
    matched_venue: str | None = None
    candidates: list[dict[str, Any]] = []
    warning: str | None = None
    evidence_breakdown: dict[str, float] | None = None
    reason: str | None = None
    field_evidence: dict[str, Any] | None = None
    source_diagnostics: dict[str, Any] | None = None
    parse_status: str | None = None
    search_attempted: bool = False
    search_strategy: str | None = None
    metadata_consistency: str | None = None
    completed_metadata: dict[str, Any] | None = None
    formatted_apa: str | None = None
    formatted_bibtex: str | None = None
    csl_json: dict[str, Any] | None = None
    resolved_url: str | None = None
    evidence_urls: list[str] = []
    resolver_chain: list[str] = []
    candidate_gap: float | None = None
    matched_by: str | None = None
    discovered_from: str | None = None
    source_domain: str | None = None
    web_search_query: str | None = None
    web_search_provider: str | None = None
    web_search_skipped_reason: str | None = None
    source_type: str | None = None
    source_number: int | None = None


class CitationBatchResultItem(CitationItem):
    index: int
    raw_citation: str
    ux_group: str
    short_issue: str | None = None
    suggested_action: str | None = None


class CitationBatchSummary(BaseModel):
    total_count: int = 0
    verified_count: int = 0
    review_count: int = 0
    problem_count: int = 0
    temporary_issue_count: int = 0
    status_counts: dict[str, int] = {}
    summary_text: str | None = None
    default_summary_text: str | None = None


class CitationReportResponse(BaseModel):
    type: str = "citation_report"
    data: list[CitationItem]
    text: str


class CitationBatchVerifyResponse(BaseModel):
    type: str = "citation_report"
    summary: CitationBatchSummary
    results: list[CitationBatchResultItem]
    text: str


class JournalMatchRequest(BaseModel):
    session_id: str
    abstract: str = Field(min_length=30)
    title: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_payload_shapes(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("abstract"):
            return data
        for key in ("text", "manuscript_text", "body_text"):
            if data.get(key):
                payload = dict(data)
                payload["abstract"] = data[key]
                return payload
        return data


class JournalLink(BaseModel):
    label: str
    url: str
    type: str


class JournalItem(BaseModel):
    id: str | None = None
    name: str | None = None
    journal: str
    venue_id: str | None = None
    venue_type: str | None = None
    entity_type: str = "venue"
    production_eligible: bool = True
    score: float | None = None
    score_calibrated: bool = False
    reason: str
    url: str | None = None
    impact_factor: float | None = None
    publisher: str | None = None
    open_access: bool = False
    issn: str | None = None
    eissn: str | None = None
    h_index: int | None = None
    review_time_weeks: int | None = None
    acceptance_rate: float | None = None
    domains: list[str] = []
    detected_domains: list[str] = []
    supporting_evidence: list[dict[str, Any]] = []
    metric_provenance: dict[str, str] = {}
    unverified_metrics: list[str] = []
    score_breakdown: dict[str, float] = {}
    warning_flags: list[str] = []
    scope_fit: str | None = None
    evidence_count: int = 0
    links: list[JournalLink] = []
    link_warning: str | None = None


class JournalMatchResponse(BaseModel):
    type: str = "journal_list"
    data: list[JournalItem]
    text: str


class RetractionScanRequest(BaseModel):
    session_id: str
    text: str = Field(..., min_length=10)


class RetractionItem(BaseModel):
    doi: str
    status: str
    title: str | None = None
    authors: list[str] = []
    pubpeer_comments: int = 0
    pubpeer_url: str | None = None
    pubpeer_status: str = "not_checked"
    has_pubpeer_discussion: bool = False
    risk_level: str = "UNKNOWN"
    has_retraction: bool = False
    has_correction: bool = False
    has_concern: bool = False
    is_retracted_openalex: bool = False
    risk_factors: list[str] = []
    journal: str | None = None
    publication_year: int | None = None
    sources_checked: list[str] = []
    scan_skipped: bool = False
    skip_reason: str | None = None


class RetractionScanResponse(BaseModel):
    type: str = "retraction_report"
    data: list[RetractionItem]
    text: str


class PdfSummaryRequest(BaseModel):
    session_id: str
    file_id: str = Field(
        ...,
        min_length=1,
        description="ID của file PDF cần tóm tắt (bắt buộc để tránh tóm tắt nhầm file).",
    )


class PdfSummaryResponse(BaseModel):
    type: str = "pdf_summary"
    file_id: str
    file_name: str
    text: str


# AI Writing Detection
class AIWritingDetectRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=50)
    mode: str = "deep"
    use_custom_rules: bool = True
    rule_ids: list[str] | None = None
    include_explanation: bool = True


class AIWritingDetectResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    score: float
    model_score: float | None = None
    roberta_score: float | None = None
    custom_rule_score: float = 0.0
    final_score: float | None = None
    risk_level: str | None = None
    verdict: str
    confidence: str
    flags: list[str]
    details: dict
    method: str = "rule_based_heuristics"
    ml_score: float | None = None
    rule_score: float = 0.0
    specter2_score: float | None = None
    skipped_detectors: list[str] = []
    fallback_reason: str | None = None
    detectors_used: list[str] = []
    rule_source: str = "default_app_rules"
    matched_rules: list[dict[str, Any] | str] = []
    evidence: list[dict[str, Any]] = []
    explanation: str | None = None
    suggestions: list[str] = []
    disclaimer: str | None = None
    warnings: list[str] = []


class AIWritingDetectResponse(BaseModel):
    type: str = "ai_writing_detection"
    data: AIWritingDetectResult
    text: str


# Grammar Checking
class GrammarCheckRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=1)


class GrammarIssue(BaseModel):
    rule_id: str
    message: str
    offset: int
    length: int
    replacements: list[str] = []
    category: str | None = None
    context: str | None = None


class GrammarCheckResult(BaseModel):
    total_errors: int
    issues: list[GrammarIssue] = []
    corrected_text: str
    error: str | None = None


class GrammarCheckResponse(BaseModel):
    type: str = "grammar_report"
    data: GrammarCheckResult
    text: str
