from typing import Any

from pydantic import BaseModel, Field, model_validator


class VerifyCitationRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=20)


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


class CitationReportResponse(BaseModel):
    type: str = "citation_report"
    data: list[CitationItem]
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


class JournalItem(BaseModel):
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


class AIWritingDetectResult(BaseModel):
    score: float
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
