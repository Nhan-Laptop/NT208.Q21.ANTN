"""
Pydantic schemas for request/response validation.

Organized by domain:
- auth: User registration, login, tokens
- admin: Admin overview and user management
- chat: Sessions, messages, completions
- tools: Scientific tool requests/responses
- upload: File upload responses
"""

from app.schemas.admin import AdminOverview, AdminUserOut
from app.schemas.academic import (
    CrawlJobOut,
    CrawlReindexRequest,
    CrawlRunRequest,
    ManuscriptAssessmentOut,
    ManuscriptOut,
    ManuscriptParseRequest,
    ManuscriptParseResponse,
    ManuscriptUploadResponse,
    MatchCandidateOut,
    MatchRequestCreate,
    MatchRequestOut,
    MatchResultResponse,
    VenueSearchItem,
    VenueSearchResponse,
)
from app.schemas.auth import PromoteUserRequest, Token, UserCreate, UserOut
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EncryptedChatCompletionResponse,
    EncryptedPayload,
    MessageOut,
    SessionChatRequest,
    SessionCreate,
    SessionOut,
    SessionUpdate,
)
from app.schemas.tools import (
    AIWritingDetectRequest,
    AIWritingDetectResponse,
    AIWritingDetectResult,
    CitationItem,
    CitationReportResponse,
    JournalItem,
    JournalMatchRequest,
    JournalMatchResponse,
    PdfSummaryRequest,
    PdfSummaryResponse,
    RetractionItem,
    RetractionScanRequest,
    RetractionScanResponse,
    VerifyCitationRequest,
)
from app.schemas.upload import FileAttachmentOut, FileUploadResponse

__all__ = [
    # Admin
    "AdminOverview",
    "AdminUserOut",
    "CrawlJobOut",
    "CrawlReindexRequest",
    "CrawlRunRequest",
    # Auth
    "ManuscriptAssessmentOut",
    "ManuscriptOut",
    "ManuscriptParseRequest",
    "ManuscriptParseResponse",
    "ManuscriptUploadResponse",
    "MatchCandidateOut",
    "MatchRequestCreate",
    "MatchRequestOut",
    "MatchResultResponse",
    "PromoteUserRequest",
    "Token",
    "UserCreate",
    "UserOut",
    # Chat
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "EncryptedChatCompletionResponse",
    "EncryptedPayload",
    "MessageOut",
    "SessionChatRequest",
    "SessionCreate",
    "SessionOut",
    "SessionUpdate",
    # Tools
    "AIWritingDetectRequest",
    "AIWritingDetectResponse",
    "AIWritingDetectResult",
    "CitationItem",
    "CitationReportResponse",
    "JournalItem",
    "JournalMatchRequest",
    "JournalMatchResponse",
    "PdfSummaryRequest",
    "PdfSummaryResponse",
    "RetractionItem",
    "RetractionScanRequest",
    "RetractionScanResponse",
    "VerifyCitationRequest",
    # Upload
    "FileAttachmentOut",
    "FileUploadResponse",
    "VenueSearchItem",
    "VenueSearchResponse",
]
