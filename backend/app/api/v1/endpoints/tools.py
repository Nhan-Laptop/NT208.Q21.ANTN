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
    CitationBatchResultItem,
    CitationBatchSummary,
    CitationBatchVerifyRequest,
    CitationBatchVerifyResponse,
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
from app.services.ai_detection_rule_service import get_runtime_rule_payloads
from app.services.ai_detection_service import ai_detection_service
from app.services.file_service import file_service
from app.services.academic_verification_formatter import format_retraction_summary
from app.services.llm_service import gemini_service
from app.services.tools.citation_batch_service import citation_batch_service
from app.services.tools.grammar_checker import grammar_checker
from app.services.tools.retraction_scan import retraction_scanner, scan_verified_retractions

try:
    from app.services.journal_match.service import build_legacy_journal_payload, journal_match_service
except Exception:  # pragma: no cover - optional heavy dependency path
    build_legacy_journal_payload = None  # type: ignore[assignment]
    journal_match_service = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])


def _persist_citation_report(
    *,
    db: Session,
    current_user: User,
    session_id: str | None,
    user_input: str,
    summary: str,
    tool_payload: dict[str, object],
) -> None:
    if not session_id:
        return

    chat_service.persist_tool_interaction(
        db=db,
        current_user=current_user,
        session_id=session_id,
        user_input=user_input,
        message_type=MessageType.CITATION_REPORT,
        summary=summary,
        tool_payload=tool_payload,
    )


@router.post(
    "/verify-citations",
    response_model=CitationBatchVerifyResponse,
    summary="Internal batch citation verification API backing chat citation verification",
)
def verify_citations(
    payload: CitationBatchVerifyRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> CitationBatchVerifyResponse:
    try:
        report = citation_batch_service.verify_text(
            payload.text,
            include_ai_summary=payload.include_ai_summary,
            max_items=payload.max_items,
        )
        summary = CitationBatchSummary(**report["summary"])
        results = [CitationBatchResultItem(**item) for item in report["results"]]

        tool_payload = {
            "type": "citation_report",
            "data": [item.model_dump() for item in results],
            "results": [item.model_dump() for item in results],
            "summary": summary.model_dump(),
            "text": report["text"],
            "statistics": report["statistics"],
            "no_citation_found": report["no_citation_found"],
        }
        _persist_citation_report(
            db=db,
            current_user=current_user,
            session_id=payload.session_id,
            user_input=payload.text,
            summary=report["text"],
            tool_payload=tool_payload,
        )

        return CitationBatchVerifyResponse(
            summary=summary,
            results=results,
            text=report["text"],
        )
    except Exception:
        logger.exception("verify_citations endpoint failed")
        raise HTTPException(
            status_code=400,
            detail="Mình chưa xác minh được danh sách trích dẫn này. Bạn có thể thử lại hoặc gửi DOI, PMID, PMCID, OpenAlex ID hoặc các dòng reference đầy đủ hơn.",
        )


@router.post(
    "/verify-citation",
    response_model=CitationReportResponse,
    summary="Legacy compatibility citation verification API backing chat citation verification",
)
def verify_citation(
    payload: VerifyCitationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> CitationReportResponse:
    try:
        report = citation_batch_service.verify_text(payload.text)
        data = [CitationItem(**item) for item in report["results"]]
        tool_payload = {
            "type": "citation_report",
            "data": [item.model_dump() for item in data],
            "results": report["results"],
            "summary": report["summary"],
            "text": report["text"],
            "statistics": report["statistics"],
            "no_citation_found": report["no_citation_found"],
        }
        _persist_citation_report(
            db=db,
            current_user=current_user,
            session_id=payload.session_id,
            user_input=payload.text,
            summary=report["text"],
            tool_payload=tool_payload,
        )

        return CitationReportResponse(data=data, text=report["text"])
    except Exception:
        logger.exception("verify_citation endpoint failed")
        raise HTTPException(
            status_code=400,
            detail="Mình chưa xác minh được trích dẫn cho nội dung này. Bạn có thể thử lại hoặc gửi DOI, PMID, PMCID, OpenAlex ID hoặc trích dẫn cụ thể hơn.",
        )


@router.post("/journal-match", response_model=JournalMatchResponse)
def journal_match(
    payload: JournalMatchRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(AccessGateway.require_permissions(Permission.TOOL_EXECUTE))],
) -> JournalMatchResponse:
    if journal_match_service is None or build_legacy_journal_payload is None:
        raise HTTPException(
            status_code=503,
            detail="Tính năng gợi ý tạp chí hiện chưa sẵn sàng trong môi trường này.",
        )
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
        runtime_rules = get_runtime_rule_payloads(
            db,
            current_user,
            use_custom_rules=payload.use_custom_rules,
            rule_ids=payload.rule_ids,
        )
        result = ai_detection_service.analyze_text(
            payload.text,
            mode=payload.mode,
            use_custom_rules=payload.use_custom_rules,
            runtime_rule_payloads=runtime_rules,
            include_explanation=payload.include_explanation,
        )
        summary = ai_detection_service.build_summary_text(result)
        data = AIWritingDetectResult.model_validate(result.model_dump(mode="json"))

        chat_service.persist_tool_interaction(
            db=db,
            current_user=current_user,
            session_id=payload.session_id,
            user_input=payload.text[:500] + ("..." if len(payload.text) > 500 else ""),
            message_type=MessageType.AI_WRITING_DETECTION,
            summary=summary,
            tool_payload=ai_detection_service.build_tool_payload(result),
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
