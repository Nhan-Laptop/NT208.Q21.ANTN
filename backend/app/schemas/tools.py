from pydantic import BaseModel, Field


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


class JournalItem(BaseModel):
    journal: str
    score: float
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
    risk_level: str = "UNKNOWN"
    has_retraction: bool = False
    has_correction: bool = False
    has_concern: bool = False
    is_retracted_openalex: bool = False
    risk_factors: list[str] = []
    journal: str | None = None
    publication_year: int | None = None
    sources_checked: list[str] = []


class RetractionScanResponse(BaseModel):
    type: str = "retraction_report"
    data: list[RetractionItem]
    text: str


class PdfSummaryRequest(BaseModel):
    session_id: str
    file_id: str | None = None


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
