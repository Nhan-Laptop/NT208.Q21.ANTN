from pydantic import BaseModel, Field


class VerifyCitationRequest(BaseModel):
    session_id: str
    text: str = Field(min_length=20)


class CitationItem(BaseModel):
    citation: str
    status: str
    evidence: str | None = None


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
    pubpeer_comments: int = 0
    pubpeer_url: str | None = None
    risk_level: str = "UNKNOWN"


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
