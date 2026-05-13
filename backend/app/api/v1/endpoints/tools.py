import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from dataclasses import asdict

from app.core.authorization import AccessGateway, Permission
from app.core.database import get_db
from app.models.chat_message import MessageType
from app.models.user import User
from app.schemas.academic import MatchRequestCreate
from app.schemas.tools import (
    AIWritingDetectRequest,
    AIWritingDetectResponse,
    AIWritingDetectResult,
    CitationItem,
    CitationReportResponse,
    GrammarCheckRequest,
    GrammarCheckResponse,
    GrammarCheckResult,
    GrammarIssue,
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
from app.services.academic_verification_formatter import (
    format_citation_summary,
    format_retraction_summary,
)
from app.services.journal_match.service import build_legacy_journal_payload, journal_match_service
from app.services.llm_service import gemini_service
from app.services.tools.ai_writing_detector import ai_writing_detector
from app.services.tools.grammar_checker import grammar_checker
from app.services.tools.citation_checker import citation_checker
from app.services.tools.retraction_scan import retraction_scanner, scan_verified_retractions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/verify-citation", response_model=CitationReportResponse)
def verify_citation(
    payload: VerifyCitationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> CitationReportResponse:
    try:
        raw_results = citation_checker.verify(payload.text)
        data = [CitationItem(**asdict(item)) for item in raw_results]
        stats = citation_checker.get_statistics(raw_results)
        summary = format_citation_summary(
            stats,
            no_citation_found=bool(stats.get("no_citation_found", False)),
        )

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
    except Exception as exc:
        logger.exception("verify_citation endpoint failed")
        raise HTTPException(
            status_code=400,
            detail="Mình chưa xác minh được trích dẫn cho nội dung này. Bạn có thể thử lại hoặc gửi DOI/trích dẫn cụ thể hơn.",
        )


@router.post("/journal-match", response_model=JournalMatchResponse)
def journal_match(
    payload: JournalMatchRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> JournalMatchResponse:
    try:
        request = journal_match_service.create_match_request(
            db,
            current_user=current_user,
            payload=MatchRequestCreate(
                text=payload.abstract,
                title=payload.title,
                session_id=payload.session_id,
                top_k=5,
                desired_venue_type="journal",
                include_cfps=False,
            ),
        )
        journal_match_service.run_request(db, current_user=current_user, request_id=request.id)
        result = journal_match_service.get_result(db, current_user=current_user, request_id=request.id)
        legacy_rows, summary = build_legacy_journal_payload(result)
        recommendations = [JournalItem(**row) for row in legacy_rows]

        chat_service.persist_tool_interaction(
            db=db,
            current_user=current_user,
            session_id=payload.session_id,
            user_input=payload.abstract,
            message_type=MessageType.JOURNAL_LIST,
            summary=summary,
            tool_payload={"type": "journal_list", "data": [x.model_dump() for x in recommendations], "request_id": request.id},
        )

        return JournalMatchResponse(data=recommendations, text=summary)
    except Exception as exc:
        logger.exception("journal_match endpoint failed")
        raise HTTPException(
            status_code=400,
            detail="Mình chưa xử lý được yêu cầu tìm kiếm tạp chí cho nội dung này. Bạn vui lòng kiểm tra lại nội dung hoặc thử lại sau.",
        )


@router.post("/retraction-scan", response_model=RetractionScanResponse)
def retraction_scan(
    payload: RetractionScanRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> RetractionScanResponse:
    try:
        raw_reports = scan_verified_retractions(payload.text)
        reports = [RetractionItem(**asdict(row)) for row in raw_reports]
        stats = retraction_scanner.get_summary(raw_reports)
        summary = format_retraction_summary(stats)

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
    except Exception as exc:
        logger.exception("retraction_scan endpoint failed")
        raise HTTPException(
            status_code=400,
            detail="Mình chưa kiểm tra retraction được cho nội dung này. Bạn vui lòng thử lại hoặc gửi DOI cụ thể hơn.",
        )


@router.post("/summarize-pdf", response_model=PdfSummaryResponse)
def summarize_pdf(
    payload: PdfSummaryRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> PdfSummaryResponse:
    try:
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
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("summarize_pdf endpoint failed")
        raise HTTPException(
            status_code=400,
            detail="Mình chưa tóm tắt được tài liệu này. Bạn vui lòng kiểm tra lại file hoặc thử lại sau.",
        )


@router.post("/detect-ai-writing", response_model=AIWritingDetectResponse)
def detect_ai_writing(
    payload: AIWritingDetectRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> AIWritingDetectResponse:
    try:
        result = ai_writing_detector.analyze(payload.text)

        verdict_labels = {
            "LIKELY_HUMAN": "✅ Văn bản có vẻ được viết bởi con người",
            "POSSIBLY_HUMAN": "🤔 Văn bản có thể được viết bởi con người",
            "UNCERTAIN": "🤔 Văn bản chưa rõ ràng, cần thêm ngữ cảnh để đánh giá",
            "POSSIBLY_AI": "⚠️ Văn bản có dấu hiệu được tạo bởi AI",
            "LIKELY_AI": "🚨 Văn bản rất có thể được tạo bởi AI",
        }
        prefix = verdict_labels.get(result.verdict, "🤔 Văn bản chưa rõ ràng")
        summary = f"{prefix} (score: {result.score:.1%}). Độ tin cậy: {result.confidence}."

        if result.flags:
            summary += f" Các dấu hiệu: {'; '.join(result.flags[:3])}."
        if result.detectors_used:
            summary += f" Detectors: {', '.join(result.detectors_used)}."
        if result.skipped_detectors:
            summary += f" Skipped: {', '.join(result.skipped_detectors)}."

        data = AIWritingDetectResult(
            score=result.score,
            verdict=result.verdict,
            confidence=result.confidence,
            flags=result.flags,
            details=result.details,
            method=result.method,
            ml_score=result.ml_score,
            rule_score=result.rule_score,
            specter2_score=result.specter2_score,
            skipped_detectors=result.skipped_detectors,
            fallback_reason=result.fallback_reason,
            detectors_used=result.detectors_used,
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
    except Exception as exc:
        logger.exception("detect_ai_writing endpoint failed")
        raise HTTPException(
            status_code=400,
            detail="Mình chưa phân tích được nội dung này. Bạn vui lòng thử lại với văn bản dài hơn.",
        )


@router.post("/ai-detect", response_model=AIWritingDetectResponse)
def detect_ai_writing_alias(
    payload: AIWritingDetectRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> AIWritingDetectResponse:
    return detect_ai_writing(payload=payload, db=db, current_user=current_user)


@router.post("/check-grammar", response_model=GrammarCheckResponse)
def check_grammar(
    payload: GrammarCheckRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> GrammarCheckResponse:
    """Check text for grammar and spelling errors using LanguageTool."""
    try:
        raw = grammar_checker.check_grammar(payload.text)

        total = raw.get("total_errors", 0)
        if total == 0:
            summary = "✅ Không phát hiện lỗi ngữ pháp hay chính tả."
        else:
            summary = f"✍️ Phát hiện {total} lỗi ngữ pháp/chính tả. Văn bản đã được sửa tự động."

        issues = [GrammarIssue(**i) for i in raw.get("issues", [])]
        data = GrammarCheckResult(
            total_errors=raw.get("total_errors", 0),
            issues=issues,
            corrected_text=raw.get("corrected_text", payload.text),
            error=raw.get("error"),
        )

        chat_service.persist_tool_interaction(
            db=db,
            current_user=current_user,
            session_id=payload.session_id,
            user_input=payload.text[:500] + ("..." if len(payload.text) > 500 else ""),
            message_type=MessageType.GRAMMAR_REPORT,
            summary=summary,
            tool_payload={"type": "grammar_report", "data": data.model_dump()},
        )

        return GrammarCheckResponse(data=data, text=summary)
    except Exception as exc:
        logger.exception("check_grammar endpoint failed")
        raise HTTPException(
            status_code=400,
            detail="Mình chưa kiểm tra ngữ pháp được cho nội dung này. Bạn vui lòng thử lại sau.",
        )
