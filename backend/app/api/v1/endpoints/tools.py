from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from dataclasses import asdict

from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.chat_message import MessageType
from app.models.user import User
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
from app.services.chat_service import chat_service
from app.services.file_service import file_service
from app.services.llm_service import gemini_service
from app.services.tools.ai_writing_detector import ai_writing_detector
from app.services.tools.citation_checker import citation_checker
from app.services.tools.journal_finder import journal_finder
from app.services.tools.retraction_scan import retraction_scanner

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/verify-citation", response_model=CitationReportResponse)
def verify_citation(
    payload: VerifyCitationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> CitationReportResponse:
    data = [CitationItem(**asdict(item)) for item in citation_checker.verify(payload.text)]
    hallucinated = [item for item in data if item.status == "HALLUCINATED"]
    summary = f"Tôi đã kiểm tra trích dẫn và phát hiện {len(hallucinated)} trích dẫn có nguy cơ hallucinated."

    chat_service.persist_tool_interaction(
        db=db,
        current_user=current_user,
        session_id=payload.session_id,
        user_input=payload.text,
        message_type=MessageType.CITATION_REPORT,
        summary=summary,
        tool_payload={"type": "citation_report", "data": [x.model_dump() for x in data]},
    )

    return CitationReportResponse(data=data, text=summary)


@router.post("/journal-match", response_model=JournalMatchResponse)
def journal_match(
    payload: JournalMatchRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> JournalMatchResponse:
    recommendations = [JournalItem(**row) for row in journal_finder.recommend(payload.abstract)]
    summary = "Tôi đã gợi ý danh sách tạp chí dựa trên độ tương đồng giữa abstract và scope của tạp chí."

    chat_service.persist_tool_interaction(
        db=db,
        current_user=current_user,
        session_id=payload.session_id,
        user_input=payload.abstract,
        message_type=MessageType.JOURNAL_LIST,
        summary=summary,
        tool_payload={"type": "journal_list", "data": [x.model_dump() for x in recommendations]},
    )

    return JournalMatchResponse(data=recommendations, text=summary)


@router.post("/retraction-scan", response_model=RetractionScanResponse)
def retraction_scan(
    payload: RetractionScanRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> RetractionScanResponse:
    reports = [RetractionItem(**asdict(row)) for row in retraction_scanner.scan(payload.text)]
    
    # Count issues
    retracted_count = sum(1 for r in reports if r.status == "RETRACTED")
    high_risk_count = sum(1 for r in reports if r.risk_level == "HIGH")
    pubpeer_count = sum(1 for r in reports if r.pubpeer_comments > 0)
    
    summary_parts = ["Tôi đã quét DOI và kiểm tra trạng thái retract bằng OpenAlex và PubPeer."]
    if retracted_count > 0:
        summary_parts.append(f"⚠️ Phát hiện {retracted_count} bài đã bị rút bỏ (RETRACTED).")
    if high_risk_count > 0:
        summary_parts.append(f"⚠️ {high_risk_count} bài có nguy cơ cao (nhiều bình luận trên PubPeer).")
    if pubpeer_count > 0:
        summary_parts.append(f"📝 {pubpeer_count} bài có bình luận trên PubPeer.")
    
    summary = " ".join(summary_parts)

    chat_service.persist_tool_interaction(
        db=db,
        current_user=current_user,
        session_id=payload.session_id,
        user_input=payload.text,
        message_type=MessageType.RETRACTION_REPORT,
        summary=summary,
        tool_payload={"type": "retraction_report", "data": [x.model_dump() for x in reports]},
    )

    return RetractionScanResponse(data=reports, text=summary)


@router.post("/summarize-pdf", response_model=PdfSummaryResponse)
def summarize_pdf(
    payload: PdfSummaryRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> PdfSummaryResponse:
    attachment = file_service.get_attachment(
        db=db,
        current_user=current_user,
        session_id=payload.session_id,
        file_id=payload.file_id,
    )
    if not attachment.extracted_text:
        return PdfSummaryResponse(
            file_id=attachment.id,
            file_name=attachment.file_name,
            text="Không có nội dung text để tóm tắt (file có thể không phải PDF text-based).",
        )

    summary_text = gemini_service.summarize_text(attachment.extracted_text)
    chat_service.persist_tool_interaction(
        db=db,
        current_user=current_user,
        session_id=payload.session_id,
        user_input=f"Tóm tắt tài liệu: {attachment.file_name}",
        message_type=MessageType.PDF_SUMMARY,
        summary=summary_text,
        tool_payload={
            "type": "pdf_summary",
            "data": {
                "file_id": attachment.id,
                "file_name": attachment.file_name,
            },
        },
    )
    return PdfSummaryResponse(
        file_id=attachment.id,
        file_name=attachment.file_name,
        text=summary_text,
    )


@router.post("/detect-ai-writing", response_model=AIWritingDetectResponse)
def detect_ai_writing(
    payload: AIWritingDetectRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> AIWritingDetectResponse:
    """
    Detect AI-generated writing using rule-based heuristics.
    
    Analyzes text for patterns commonly found in AI-generated content:
    - Vocabulary diversity (TTR)
    - Sentence structure uniformity
    - Common AI phrases and patterns
    - Repetitive structures
    """
    result = ai_writing_detector.analyze(payload.text)
    verdict = ai_writing_detector.get_verdict(result.score)
    
    # Build summary message
    if result.score < 0.3:
        summary = f"✅ Văn bản có vẻ được viết bởi con người (score: {result.score:.1%}). Độ tin cậy: {result.confidence}."
    elif result.score < 0.5:
        summary = f"🤔 Văn bản có thể được viết bởi con người (score: {result.score:.1%}). Độ tin cậy: {result.confidence}."
    elif result.score < 0.7:
        summary = f"⚠️ Văn bản có dấu hiệu được tạo bởi AI (score: {result.score:.1%}). Độ tin cậy: {result.confidence}."
    else:
        summary = f"🚨 Văn bản rất có thể được tạo bởi AI (score: {result.score:.1%}). Độ tin cậy: {result.confidence}."
    
    if result.flags:
        summary += f" Các dấu hiệu: {'; '.join(result.flags[:3])}."

    data = AIWritingDetectResult(
        score=result.score,
        verdict=verdict,
        confidence=result.confidence,
        flags=result.flags,
        details=result.details,
    )

    chat_service.persist_tool_interaction(
        db=db,
        current_user=current_user,
        session_id=payload.session_id,
        user_input=payload.text[:500] + ("..." if len(payload.text) > 500 else ""),
        message_type=MessageType.AI_WRITING_DETECTION,
        summary=summary,
        tool_payload={"type": "ai_writing_detection", "data": data.model_dump()},
    )

    return AIWritingDetectResponse(data=data, text=summary)


@router.post("/ai-detect", response_model=AIWritingDetectResponse)
def detect_ai_writing_alias(
    payload: AIWritingDetectRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> AIWritingDetectResponse:
    return detect_ai_writing(payload=payload, db=db, current_user=current_user)
