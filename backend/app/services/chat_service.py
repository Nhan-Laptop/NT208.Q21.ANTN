import logging
from dataclasses import asdict
import re
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session, selectinload

from app.core.authorization import AccessGateway
from app.core.config import settings
from app.models.chat_message import ChatMessage, MessageRole, MessageType
from app.models.chat_session import ChatSession, SessionMode
from app.models.file_attachment import FileAttachment
from app.models.article import Article
from app.models.venue import Venue
from app.models.user import User
from app.schemas.academic import MatchRequestCreate
from app.services.academic_query_service import academic_query_service
from app.services.academic_policy import (
    AIRA_GENERAL_ACADEMIC_PROMPT,
    EXACT_RECORD_NOT_FOUND_MESSAGE,
    USER_SAFE_CORPUS_LABEL,
    USER_SAFE_DATA_LABEL,
    sanitize_user_payload,
    sanitize_user_text,
)
from app.services.academic_verification_formatter import (
    format_citation_summary,
    format_retraction_summary,
)
from app.services.ai_detection_rules import get_user_ai_detection_rule_phrases
from app.services.auto_intent_router import (
    FEATURE_AI_DETECTION,
    FEATURE_DOI_METADATA,
    FEATURE_GENERAL_QA,
    FEATURE_GRAMMAR,
    FEATURE_JOURNAL_MATCH,
    FEATURE_LABELS,
    FEATURE_RETRACTION,
    FEATURE_VERIFICATION,
    AutoIntentResult,
    auto_intent_router,
)
from app.services.llm_service import gemini_service
from app.services.journal_match.topic_profile import ManuscriptTopicProfile
from app.services.tools.ai_writing_detector import ai_writing_detector
from app.services.tools.citation_checker import citation_checker
from app.services.tools.grammar_checker import grammar_checker
from app.services.tools.retraction_scan import retraction_scanner, scan_verified_retractions

try:
    from app.services.journal_match.service import build_legacy_journal_payload, journal_match_service
except Exception:  # pragma: no cover - optional heavy dependency path
    build_legacy_journal_payload = None  # type: ignore[assignment]
    journal_match_service = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class ChatService:
    DEFAULT_SESSION_TITLE = "Trò chuyện mới"
    _LEGACY_DEFAULT_TITLES = {"new chat", "trò chuyện mới"}
    _MODE_DEFAULT_TITLES: dict[SessionMode, str] = {
        SessionMode.AUTO: "Trò chuyện mới",
        SessionMode.GENERAL_QA: "Trò chuyện mới",
        SessionMode.VERIFICATION: "Xác minh trích dẫn",
        SessionMode.JOURNAL_MATCH: "Gợi ý tạp chí",
        SessionMode.RETRACTION: "Kiểm tra retraction",
        SessionMode.AI_DETECTION: "Phát hiện AI",
    }
    FILE_HINT_PATTERN = re.compile(r"\b(pdf|file|document|paper|manuscript|tom tat|summary|summarize)\b", re.IGNORECASE)
    JOURNAL_FOLLOWUP_PATTERN = re.compile(
        r"\b("
        r"giới\s*thiệu|gioi\s*thieu|explain|introduce|so\s*sánh|so\s+sanh|compare|"
        r"nói\s*rõ|noi\s*ro|nói\s*kỹ|noi\s*ky|chi\s*tiết|chi\s+tiet|từng\s+journal|tung\s+journal|"
        r"các\s+journal\s+trên|cac\s+journal\s+tren|từng\s+gợi\s+ý|tung\s+goi\s+y|each\s+journal"
        r")\b",
        re.IGNORECASE,
    )
    JOURNAL_INTENT_PATTERN = re.compile(
        r"\b("
        r"gợi\s*ý\s*tạp\s*chí|đề\s*xuất\s*tạp\s*chí|journal\s+recommendation|"
        r"journal\s+match|nơi\s*nộp\s*bài|tìm\s*tạp\s*chí|"
        r"suitable\s+journal|similar\s+manuscript|recommend\s+journal|"
        r"nơi\s+đăng|tạp\s*chí\s+phù\s*hợp|gợi\s+ý\s+journal"
        r")\b",
        re.IGNORECASE,
    )
    CITATION_VERIFY_PATTERN = re.compile(
        r"\b("
        r"xác\s*minh\s*trích\s*dẫn|verify\s+citation|citation\s+check|"
        r"kiểm\s*tra\s*doi|verify\s+doi"
        r")\b",
        re.IGNORECASE,
    )
    DOI_METADATA_REQUEST_PATTERN = re.compile(
        r"\b("
        r"analyze|phân\s*tích|provide|show|extract|list|"
        r"thông\s*tin\s+về|thong\s*tin\s+ve|information\s+about|"
        r"doi\s+info|doi\s+metadata|metadata\s+doi|metadata|paper\s+info|"
        r"abstract|summary"
        r")\b",
        re.IGNORECASE,
    )
    DOI_INFO_PATTERN = re.compile(
        r"\b("
        r"thông\s*tin\s*về|thong\s*tin\s+ve|information\s+about|doi\s+info|"
        r"doi\s+metadata|metadata\s+doi|paper\s+info|bài\s+báo\s+về|"
        r"analyze|phân\s*tích|provide|title|journal|publisher|"
        r"publication\s*year|research\s*field|lĩnh\s*vực|"
        r"main\s*topic|chủ\s*đề|abstract|summary"
        r")\b",
        re.IGNORECASE,
    )
    DOI_METADATA_FIELD_PATTERNS = (
        re.compile(r"\btitle\b", re.IGNORECASE),
        re.compile(r"\bjournal\b", re.IGNORECASE),
        re.compile(r"\bpublisher\b", re.IGNORECASE),
        re.compile(r"\bpublication\s*year\b", re.IGNORECASE),
        re.compile(r"\bresearch\s*field\b", re.IGNORECASE),
        re.compile(r"\bmain\s*topic\b", re.IGNORECASE),
        re.compile(r"\bmetadata\b", re.IGNORECASE),
        re.compile(r"\babstract\b", re.IGNORECASE),
        re.compile(r"\bsummary\b", re.IGNORECASE),
        re.compile(r"\blĩnh\s*vực\b", re.IGNORECASE),
        re.compile(r"\bchủ\s*đề\b", re.IGNORECASE),
        re.compile(r"\btạp\s*chí\b", re.IGNORECASE),
        re.compile(r"\bnăm\s*xuất\s*bản\b", re.IGNORECASE),
    )
    _FILE_CONTEXT_MAX_CHARS = 15_000

    # ── Intent classification patterns ────────────────────────────────────
    _CORPUS_INTENT_RE = re.compile(
        r"("
        r"10\.\d{4,9}/|"  # DOI
        r"xác\s*minh\s*trích\s*dẫn|verify\s+citation|verify\s+doi|"
        r"kiểm\s*tra\s*doi|doi\s+check|citation\s+check|reference\s+check|"
        r"rút\s*bài|retract|pubpeer|thu\s*hồi|"
        r"gợi\s*ý\s*tạp\s*chí|đề\s*xuất\s*tạp\s*chí|journal\s+match|journal\s+recommendation|"
        r"bài\s+trong|crawler\s*db|cơ\s*sở\s*dữ\s*liệu|co\s*so\s*du\s*lieu|database|"
        r"xác\s*minh|xac\s*minh|trích\s*dẫn|trich\s*dan|"
        r"scan\s+retraction|detect\s+ai|phát\s*hiện\s*ai"
        r")",
        re.IGNORECASE,
    )
    _GENERAL_ACADEMIC_DISCUSSION_RE = re.compile(
        r"\b("
        r"hướng\s*nghiên\s*cứu|huong\s*nghien\s*cuu|"
        r"tiềm\s*năng|tiem\s*nang|potential|"
        r"research\s+direction|research\s+trend|"
        r"nghiên\s*cứu\s+về|nghien\s*cuu\s*ve|"
        r"nên\s+nghiên\s*cứu|nen\s+nghien\s*cuu|"
        r"lĩnh\s*vực|linh\s*vuc|field\s+of\s+research|"
        r"phương\s*pháp|phuong\s*phap|methodology|"
        r"brainstorm|ý\s*tưởng|y\s+tuong|idea|"
        r"chủ\s*đề|chu\s*de|topic|"
        r"tư\s*vấn|tu\s+van|advise|"
        r"nhận\s*định|nhan\s*dinh|assessment\s+of|"
        r"\btrend\b|\btopic\b"
        r")\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _classify_academic_intent(text: str) -> str:
        """Classify user intent into corpus_query, general_academic_discussion, or unknown.

        Returns:
            "corpus_query": User explicitly asks for corpus/tool-based lookup (DOI, citation, retraction, etc.)
            "general_academic_discussion": User asks for conceptual discussion, research direction advice, etc.
            "unknown": Cannot determine intent; falls through to normal Groq path.
        """
        normalized = (text or "").strip()
        if not normalized:
            return "unknown"

        # Corpus/tool intent takes priority over general discussion
        if ChatService._CORPUS_INTENT_RE.search(normalized):
            return "corpus_query"

        if ChatService._GENERAL_ACADEMIC_DISCUSSION_RE.search(normalized):
            return "general_academic_discussion"

        return "unknown"

    def create_session(self, db: Session, current_user: User, title: str, mode: SessionMode) -> ChatSession:
        clean_title = (title or "").strip() or self._MODE_DEFAULT_TITLES.get(mode, self.DEFAULT_SESSION_TITLE)
        session_obj = ChatSession(user_id=current_user.id, title=clean_title, mode=mode)
        db.add(session_obj)
        db.commit()
        db.refresh(session_obj)
        return session_obj

    def list_sessions(
        self,
        db: Session,
        current_user: User,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatSession]:
        query = db.query(ChatSession)
        if not current_user.is_admin:
            query = query.filter(ChatSession.user_id == current_user.id)
        return query.order_by(desc(ChatSession.updated_at)).offset(offset).limit(limit).all()

    def list_messages(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[ChatMessage]:
        AccessGateway.assert_session_access(db, current_user, session_id)
        return (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def _save_message(
        self,
        db: Session,
        session_id: str,
        role: MessageRole,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        tool_results: dict[str, Any] | list[Any] | None = None,
    ) -> ChatMessage:
        if role == MessageRole.ASSISTANT:
            if content:
                content = sanitize_user_text(content)
            if tool_results is not None:
                tool_results = sanitize_user_payload(tool_results)

        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            message_type=message_type,
            tool_results=tool_results,
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message

    def _is_default_title(self, title: str | None, mode: SessionMode = SessionMode.GENERAL_QA) -> bool:
        normalized = (title or "").strip().lower()
        if normalized in self._LEGACY_DEFAULT_TITLES:
            return True
        mode_default = self._MODE_DEFAULT_TITLES.get(mode, "Trò chuyện mới")
        return normalized == mode_default.lower()

    def _latest_journal_list_message(self, db: Session, session_id: str) -> ChatMessage | None:
        return (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.ASSISTANT,
                ChatMessage.message_type == MessageType.JOURNAL_LIST,
            )
            .order_by(desc(ChatMessage.created_at))
            .first()
        )

    def _build_journal_followup_payload(
        self,
        db: Session,
        session_id: str,
        user_message: str,
    ) -> tuple[str, dict[str, Any]] | None:
        if not self.JOURNAL_FOLLOWUP_PATTERN.search(user_message or ""):
            return None
        previous = self._latest_journal_list_message(db, session_id)
        if previous is None or not isinstance(previous.tool_results, dict):
            return None
        if previous.tool_results.get("type") != "journal_list":
            return None
        rows = previous.tool_results.get("data")
        if not isinstance(rows, list):
            return None

        lines = [
            "Mình sẽ giải thích lại đúng danh sách journal đã gợi ý ở lượt trước; không chạy lại ranking mới."
        ]
        if not rows:
            lines.append(
                "Lượt trước không có candidate đủ điều kiện; mình giữ nguyên kết luận thiếu dữ liệu thay vì tạo danh sách mới."
            )
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            name = row.get("journal") or row.get("venue_id") or f"Journal #{index}"
            reason = str(row.get("reason") or "Gợi ý này dựa trên dữ liệu học thuật hiện có.")
            domains = row.get("domains") if isinstance(row.get("domains"), list) else []
            evidence = row.get("supporting_evidence") if isinstance(row.get("supporting_evidence"), list) else []
            domain_text = f" Chủ đề ghi nhận: {', '.join(str(item) for item in domains[:4])}." if domains else ""
            evidence_titles = [
                str(item.get("title"))
                for item in evidence
                if isinstance(item, dict) and item.get("title")
            ]
            evidence_text = f" Evidence phụ: {'; '.join(evidence_titles[:2])}." if evidence_titles else ""
            lines.append(f"{index}. {name}: {reason}{domain_text}{evidence_text}")

        payload = {
            **previous.tool_results,
            "source": "prior_journal_list_followup",
            "reused_from_message_id": previous.id,
        }
        return "\n".join(lines), payload

    def _run_mode_tool(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        mode: SessionMode,
        text: str,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        if mode == SessionMode.VERIFICATION:
            try:
                citation_results = citation_checker.verify(text)
                data = [asdict(item) for item in citation_results]
                stats = citation_checker.get_statistics(citation_results)
                summary = format_citation_summary(
                    stats,
                    no_citation_found=bool(stats.get("no_citation_found", False)),
                    results=citation_results,
                )
                return MessageType.CITATION_REPORT, summary, {"type": "citation_report", "data": data}
            except Exception as exc:
                logger.exception("VERIFICATION mode failed for session %s", session_id)
                return MessageType.TEXT, (
                    "Mình chưa xác minh được trích dẫn cho nội dung này. "
                    "Bạn có thể thử lại hoặc gửi DOI/trích dẫn cụ thể hơn."
                ), {"type": "text", "error": str(exc)}

        if mode == SessionMode.JOURNAL_MATCH:
            if journal_match_service is None or build_legacy_journal_payload is None:
                return MessageType.TEXT, (
                    "Tính năng gợi ý tạp chí hiện chưa sẵn sàng trong môi trường này. "
                    "Bạn vui lòng thử lại sau."
                ), {"type": "text", "error": "journal_match_service_unavailable"}
            try:
                request = journal_match_service.create_match_request(
                    db,
                    current_user=current_user,
                    payload=MatchRequestCreate(
                        text=text,
                        session_id=session_id,
                        top_k=5,
                        desired_venue_type="journal",
                        include_cfps=False,
                    ),
                )
                journal_match_service.run_request(db, current_user=current_user, request_id=request.id)
                result = journal_match_service.get_result(db, current_user=current_user, request_id=request.id)
                journals, summary = build_legacy_journal_payload(result)
                diagnostics = getattr(result.get("request"), "retrieval_diagnostics", None) or {}
                candidate_ids = [
                    row.get("candidate_id") or row.get("venue_id")
                    for row in journals
                    if isinstance(row, dict) and (row.get("candidate_id") or row.get("venue_id"))
                ]
                return MessageType.JOURNAL_LIST, summary, {
                    "type": "journal_list",
                    "data": journals,
                    "request_id": request.id,
                    "candidate_ids": candidate_ids,
                    "status": diagnostics.get("match_status") or ("matched" if journals else "insufficient_evidence"),
                }
            except Exception as exc:
                logger.exception("JOURNAL_MATCH mode failed for session %s", session_id)
                return MessageType.TEXT, (
                    "Mình chưa xử lý được yêu cầu tìm kiếm tạp chí cho nội dung này. "
                    "Bạn vui lòng kiểm tra lại nội dung hoặc thử lại sau."
                ), {"type": "text", "error": str(exc)}

        if mode == SessionMode.RETRACTION:
            try:
                raw_results = scan_verified_retractions(text)
                retraction = [asdict(item) for item in raw_results]
                stats = retraction_scanner.get_summary(raw_results)
                summary = format_retraction_summary(stats)
                return MessageType.RETRACTION_REPORT, summary, {"type": "retraction_report", "data": retraction}
            except Exception as exc:
                logger.exception("RETRACTION mode failed for session %s", session_id)
                return MessageType.TEXT, (
                    "Mình chưa kiểm tra retraction được cho nội dung này. "
                    "Bạn vui lòng thử lại hoặc gửi DOI cụ thể hơn."
                ), {"type": "text", "error": str(exc)}

        if mode == SessionMode.AI_DETECTION:
            try:
                result = ai_writing_detector.analyze(
                    text,
                    custom_rule_phrases=get_user_ai_detection_rule_phrases(current_user),
                )
                data = asdict(result)
                summary = f"AI writing detection: score={data['score']}, verdict={data['verdict']}."
                return MessageType.AI_WRITING_DETECTION, summary, {"type": "ai_writing_detection", "data": data}
            except Exception as exc:
                logger.exception("AI_DETECTION mode failed for session %s", session_id)
                return MessageType.TEXT, (
                    "Mình chưa phân tích được nội dung này. "
                    "Bạn vui lòng thử lại với văn bản dài hơn."
                ), {"type": "text", "error": str(exc)}

        # Fallback (should not reach here)
        try:
            retraction = [asdict(item) for item in scan_verified_retractions(text)]
            summary = "Retraction scan completed on detected DOI(s)."
            return MessageType.RETRACTION_REPORT, summary, {"type": "retraction_report", "data": retraction}
        except Exception as exc:
            logger.exception("Fallback mode failed for session %s", session_id)
            return MessageType.TEXT, "Mình chưa xử lý được yêu cầu này. Bạn vui lòng thử lại sau.", {"type": "text", "error": str(exc)}

    def _run_grammar_tool(
        self,
        session_id: str,
        text: str,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        try:
            raw = grammar_checker.check_grammar(text)
            total = raw.get("total_errors", 0)
            if total == 0:
                summary = "✅ Không phát hiện lỗi ngữ pháp hay chính tả."
            else:
                summary = f"✍️ Phát hiện {total} lỗi ngữ pháp/chính tả. Văn bản đã được sửa tự động."
            return MessageType.GRAMMAR_REPORT, summary, {"type": "grammar_report", "data": raw}
        except Exception as exc:
            logger.exception("GRAMMAR mode failed for session %s", session_id)
            return MessageType.TEXT, (
                "Mình chưa kiểm tra ngữ pháp được cho nội dung này. "
                "Bạn vui lòng thử lại sau."
            ), {"type": "text", "error": str(exc)}

    @staticmethod
    def _with_routing_meta(
        tool_results: dict[str, Any] | list[Any] | None,
        route: AutoIntentResult,
    ) -> dict[str, Any]:
        routing = route.to_routing_dict()
        if isinstance(tool_results, dict):
            payload = dict(tool_results)
            meta = payload.get("meta")
            payload["meta"] = {
                **(meta if isinstance(meta, dict) else {}),
                "routing": routing,
            }
            return payload
        return {"meta": {"routing": routing}}

    @staticmethod
    def _feature_from_payload(
        message_type: MessageType,
        tool_results: dict[str, Any] | list[Any] | None,
    ) -> str | None:
        if message_type == MessageType.CITATION_REPORT:
            return FEATURE_VERIFICATION
        if message_type == MessageType.JOURNAL_LIST:
            return FEATURE_JOURNAL_MATCH
        if message_type == MessageType.RETRACTION_REPORT:
            return FEATURE_RETRACTION
        if message_type == MessageType.AI_WRITING_DETECTION:
            return FEATURE_AI_DETECTION
        if message_type == MessageType.GRAMMAR_REPORT:
            return FEATURE_GRAMMAR
        if isinstance(tool_results, dict) and tool_results.get("type") == "doi_metadata":
            return FEATURE_DOI_METADATA
        return None

    def _finalize_auto_response(
        self,
        route: AutoIntentResult,
        message_type: MessageType,
        content: str,
        tool_results: dict[str, Any] | list[Any] | None,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        resolved_feature = self._feature_from_payload(message_type, tool_results)
        if resolved_feature and resolved_feature != route.resolved_feature:
            route = AutoIntentResult(
                resolved_feature=resolved_feature,
                resolved_label=FEATURE_LABELS.get(resolved_feature, resolved_feature),
                confidence=route.confidence,
                source=f"{route.source}+response_shape",
                candidates=route.candidates,
                is_ambiguous=route.is_ambiguous,
            )
        return message_type, content, self._with_routing_meta(tool_results, route)

    @staticmethod
    def _build_intent_disambiguation(route: AutoIntentResult) -> tuple[MessageType, str, dict[str, Any]]:
        candidate_labels = [candidate.label for candidate in route.candidates[:3]]
        if len(candidate_labels) == 1:
            content = f"Mình chưa chắc bạn muốn dùng {candidate_labels[0]}. Bạn có thể nói rõ hơn yêu cầu không?"
        else:
            options = "; ".join(
                f"{index + 1}. {label}" for index, label in enumerate(candidate_labels)
            )
            content = (
                "Mình thấy prompt này có thể thuộc nhiều tính năng. "
                f"Bạn muốn mình dùng lựa chọn nào: {options}?"
            )
        payload = {
            "type": "intent_disambiguation",
            "data": {
                "candidates": [candidate.to_dict() for candidate in route.candidates],
            },
        }
        return MessageType.TEXT, content, ChatService._with_routing_meta(payload, route)

    def _get_file_context(self, db: Session, session_id: str) -> str | None:
        """Retrieve extracted text from the most recent file in this session.

        Returns an XML-tagged block or *None* if no usable file exists.
        The text is already decrypted by SQLAlchemy's EncryptedText type.
        """
        latest_file = (
            db.query(FileAttachment)
            .filter(FileAttachment.session_id == session_id)
            .order_by(desc(FileAttachment.created_at))
            .first()
        )
        if not latest_file or not latest_file.extracted_text:
            return None
        snippet = latest_file.extracted_text[: self._FILE_CONTEXT_MAX_CHARS]
        return (
            f'<Attached_Document name="{latest_file.file_name}">\n'
            f'{snippet}\n'
            f'</Attached_Document>'
        )

    def _build_file_context(self, db: Session, session_id: str, user_message: str) -> str:
        """Append file context to the user message when a file is attached."""
        file_block = self._get_file_context(db, session_id)
        if not file_block:
            return user_message
        return f"{user_message}\n\n{file_block}"

    def _extract_first_doi(self, text: str) -> str | None:
        dois = citation_checker.extract_dois(text or "")
        if not dois:
            return None
        return citation_checker.normalize_doi(dois[0])

    def _is_doi_metadata_request(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized or not self._extract_first_doi(normalized):
            return False
        field_hits = sum(1 for pattern in self.DOI_METADATA_FIELD_PATTERNS if pattern.search(normalized))
        has_request_phrase = bool(self.DOI_METADATA_REQUEST_PATTERN.search(normalized))
        has_info_phrase = bool(self.DOI_INFO_PATTERN.search(normalized))
        return has_info_phrase and (has_request_phrase or field_hits >= 3)

    @staticmethod
    def _clean_metadata_text(value: str | None) -> str | None:
        if not value:
            return None
        text = re.sub(r"<[^>]+>", " ", str(value))
        text = re.sub(r"\s+", " ", text).strip()
        return text or None

    @staticmethod
    def _decode_openalex_abstract(payload: dict[str, Any]) -> str | None:
        abstract = payload.get("abstract")
        if isinstance(abstract, str) and abstract.strip():
            return abstract.strip()

        inverted = payload.get("abstract_inverted_index")
        if not isinstance(inverted, dict) or not inverted:
            return None

        size = 0
        for positions in inverted.values():
            if not isinstance(positions, list):
                continue
            for pos in positions:
                if isinstance(pos, int):
                    size = max(size, pos + 1)
        if size <= 0:
            return None

        tokens = [""] * size
        for word, positions in inverted.items():
            if not isinstance(word, str) or not isinstance(positions, list):
                continue
            for pos in positions:
                if isinstance(pos, int) and 0 <= pos < size:
                    tokens[pos] = word
        text = " ".join(token for token in tokens if token).strip()
        return text or None

    @staticmethod
    def _dedupe_text_list(values: list[Any] | None) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(text)
        return deduped

    @staticmethod
    def _display_source_label(source: str | None) -> str | None:
        normalized = (source or "").strip().lower()
        if not normalized:
            return None
        if "crossref" in normalized:
            return "Crossref"
        if "openalex" in normalized or normalized == "pyalex":
            return "OpenAlex"
        if "semantic" in normalized:
            return "Semantic Scholar"
        return source

    @classmethod
    def _missing_metadata_note_prefix(cls, source_label: str | None) -> str:
        normalized = (source_label or "").lower()
        if "crossref" in normalized or "openalex" in normalized or "semantic" in normalized:
            return "Not directly available from Crossref/OpenAlex metadata."
        return "Not directly available from the verified metadata source."

    @classmethod
    def _derive_research_field(
        cls,
        *,
        subjects: list[str],
        keywords: list[str],
        source_label: str | None,
    ) -> tuple[str | None, str, str | None]:
        if subjects:
            return subjects[0], "source", None
        if keywords:
            return (
                keywords[0],
                "inferred",
                f"{cls._missing_metadata_note_prefix(source_label)} Inferred from source keywords.",
            )
        return None, "unavailable", cls._missing_metadata_note_prefix(source_label)

    @classmethod
    def _derive_main_topic(
        cls,
        *,
        title: str | None,
        keywords: list[str],
        subjects: list[str],
        source_label: str | None,
    ) -> tuple[str | None, str, str | None]:
        keyword_topic = ", ".join(keywords[:3]).strip()
        if keyword_topic:
            return keyword_topic, "source", None
        if title:
            return (
                title,
                "inferred",
                f"{cls._missing_metadata_note_prefix(source_label)} Inferred from the article title.",
            )
        if subjects:
            return (
                subjects[0],
                "inferred",
                f"{cls._missing_metadata_note_prefix(source_label)} Inferred from subject terms.",
            )
        return None, "unavailable", cls._missing_metadata_note_prefix(source_label)

    @classmethod
    def _build_doi_metadata_payload(
        cls,
        *,
        doi: str,
        status: str,
        source: str | None,
        confidence: float | None,
        title: str | None,
        abstract: str | None,
        publication_year: int | None,
        journal: str | None,
        publisher: str | None,
        authors: list[Any] | None,
        subjects: list[Any] | None,
        keywords: list[Any] | None,
        url: str | None,
    ) -> dict[str, Any]:
        cleaned_title = cls._clean_metadata_text(title)
        cleaned_abstract = cls._clean_metadata_text(abstract)
        cleaned_journal = cls._clean_metadata_text(journal)
        cleaned_publisher = cls._clean_metadata_text(publisher)
        cleaned_authors = cls._dedupe_text_list(authors)
        cleaned_subjects = cls._dedupe_text_list(subjects)
        cleaned_keywords = cls._dedupe_text_list(keywords)
        source_label = cls._display_source_label(source) or source

        research_field, research_field_basis, research_field_note = cls._derive_research_field(
            subjects=cleaned_subjects,
            keywords=cleaned_keywords,
            source_label=source_label,
        )
        main_topic, main_topic_basis, main_topic_note = cls._derive_main_topic(
            title=cleaned_title,
            keywords=cleaned_keywords,
            subjects=cleaned_subjects,
            source_label=source_label,
        )

        missing_fields: list[str] = []
        if not cleaned_title:
            missing_fields.append("title")
        if not cleaned_journal:
            missing_fields.append("journal")
        if not cleaned_publisher:
            missing_fields.append("publisher")
        if publication_year is None:
            missing_fields.append("publication_year")
        if not research_field:
            missing_fields.append("research_field")
        if not main_topic:
            missing_fields.append("main_topic")

        notes: list[str] = []
        for note in (research_field_note, main_topic_note):
            if note and note not in notes:
                notes.append(note)

        return {
            "status": status,
            "doi": doi,
            "title": cleaned_title,
            "abstract": cleaned_abstract,
            "year": publication_year,
            "publication_year": publication_year,
            "venue": cleaned_journal,
            "journal": cleaned_journal,
            "publisher": cleaned_publisher,
            "authors": cleaned_authors,
            "subjects": cleaned_subjects,
            "keywords": cleaned_keywords,
            "research_field": research_field,
            "research_field_basis": research_field_basis,
            "research_field_note": research_field_note,
            "main_topic": main_topic,
            "main_topic_basis": main_topic_basis,
            "main_topic_note": main_topic_note,
            "url": url,
            "verification_status": "Valid DOI" if status == "verified" else "DOI not found",
            "confidence": float(confidence or 0.0),
            "source": source_label or source,
            "missing_fields": missing_fields,
            "notes": notes,
        }

    def _resolve_doi_metadata(self, db: Session, doi: str) -> tuple[dict[str, Any], str]:
        normalized = citation_checker.normalize_doi(doi)
        article = (
            db.query(Article)
            .options(
                selectinload(Article.authors),
                selectinload(Article.keywords),
                selectinload(Article.venue).selectinload(Venue.subjects),
            )
            .filter(func.lower(Article.doi) == normalized)
            .first()
        )
        if article is not None:
            subjects = []
            if article.venue and getattr(article.venue, "subjects", None):
                subjects = [subject.label for subject in article.venue.subjects if subject.label]
            keywords = [keyword.keyword for keyword in article.keywords if keyword.keyword]
            authors = [author.full_name for author in article.authors if author.full_name]
            metadata = self._build_doi_metadata_payload(
                doi=normalized,
                status="verified",
                source=USER_SAFE_CORPUS_LABEL,
                confidence=1.0,
                title=article.title,
                abstract=article.abstract,
                publication_year=article.publication_year,
                journal=article.venue.title if article.venue else None,
                publisher=article.publisher or (article.venue.publisher if article.venue else None),
                authors=authors,
                subjects=subjects,
                keywords=keywords,
                url=article.url,
            )
            return metadata, "verified"

        result = citation_checker.verify_doi_exact(normalized)
        if result.status != "DOI_VERIFIED":
            metadata = self._build_doi_metadata_payload(
                doi=normalized,
                status="not_found",
                source=result.source,
                confidence=result.confidence,
                title=None,
                abstract=None,
                publication_year=None,
                journal=None,
                publisher=None,
                authors=[],
                subjects=[],
                keywords=[],
                url=None,
            )
            return metadata, "not_found"

        meta = result.metadata or {}
        crossref = meta.get("crossref") or {}
        openalex = meta.get("openalex") or {}
        if not openalex:
            try:
                openalex_result = citation_checker._verify_doi_openalex_exact(normalized)
                if openalex_result and isinstance(openalex_result.metadata, dict):
                    openalex = openalex_result.metadata.get("openalex") or {}
            except Exception:
                logger.debug("OpenAlex enrichment failed for DOI metadata lookup %s", normalized, exc_info=True)

        subjects: list[str] = []
        if crossref.get("subject"):
            subjects = [str(item).strip() for item in crossref.get("subject", []) if str(item).strip()]
        elif openalex.get("concepts"):
            subjects = [
                str(item.get("display_name")).strip()
                for item in openalex.get("concepts", [])
                if item.get("display_name")
            ]

        keywords: list[str] = []
        if openalex.get("keywords"):
            keywords = [
                str(item.get("display_name") or item.get("keyword")).strip()
                for item in openalex.get("keywords", [])
                if item.get("display_name") or item.get("keyword")
            ]

        venue = None
        if crossref.get("container-title"):
            venue = str(crossref.get("container-title", [""])[0]).strip() or None
        elif isinstance(openalex.get("primary_location"), dict):
            primary_source = openalex.get("primary_location", {}).get("source") or {}
            venue = primary_source.get("display_name")
        elif openalex.get("host_venue"):
            venue = openalex.get("host_venue", {}).get("display_name")

        openalex_authors = [
            str(item.get("author", {}).get("display_name")).strip()
            for item in openalex.get("authorships", [])
            if item.get("author", {}).get("display_name")
        ]
        metadata = self._build_doi_metadata_payload(
            doi=normalized,
            status="verified",
            source=result.source,
            confidence=result.confidence,
            title=result.title,
            abstract=self._clean_metadata_text(crossref.get("abstract"))
            or self._decode_openalex_abstract(openalex),
            publication_year=result.year,
            journal=venue,
            publisher=self._clean_metadata_text(crossref.get("publisher")),
            authors=result.authors or openalex_authors,
            subjects=subjects,
            keywords=keywords,
            url=crossref.get("URL") or openalex.get("id"),
        )
        return metadata, "verified"

    def _build_manuscript_text(self, metadata: dict[str, Any]) -> str:
        parts: list[str] = []
        title = str(metadata.get("title") or "").strip()
        abstract = str(metadata.get("abstract") or "").strip()
        subjects = metadata.get("subjects") or []
        keywords = metadata.get("keywords") or []
        if title:
            parts.append(f"Title: {title}")
        if abstract:
            parts.append(abstract)
        if subjects:
            parts.append("Subjects: " + ", ".join(str(item) for item in subjects[:8]))
        if keywords:
            parts.append("Keywords: " + ", ".join(str(item) for item in keywords[:10]))
        return "\n".join(part for part in parts if part)

    def _run_doi_metadata_lookup(self, db: Session, doi: str) -> tuple[MessageType, str, dict[str, Any]]:
        metadata, status = self._resolve_doi_metadata(db, doi)
        if status != "verified":
            text = (
                "Mình chưa xác minh được DOI này nên không tạo metadata suy đoán. "
                f"{EXACT_RECORD_NOT_FOUND_MESSAGE} "
                f"Bạn có thể cung cấp thêm tiêu đề, tác giả, hoặc abstract để mình kiểm tra lại trong {USER_SAFE_DATA_LABEL}."
            )
        else:
            text = (
                "Mình đã xác minh DOI và trích xuất metadata chi tiết cho bài báo này. "
                "Bạn có thể xem title, journal, publisher, publication year, research field, main topic, confidence và source ở thẻ kết quả bên dưới."
            )
        payload = {
            "type": "doi_metadata",
            "status": status,
            "data": metadata,
        }
        return MessageType.TEXT, text, payload

    def _run_journal_match_from_doi(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        doi: str,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        if journal_match_service is None or build_legacy_journal_payload is None:
            return MessageType.TEXT, (
                "Tính năng gợi ý tạp chí hiện chưa sẵn sàng trong môi trường này. "
                "Bạn vui lòng thử lại sau."
            ), {"type": "text", "error": "journal_match_service_unavailable"}

        metadata, status = self._resolve_doi_metadata(db, doi)
        if status != "verified":
            summary = (
                f"Mình chưa tìm thấy metadata phù hợp trong {USER_SAFE_DATA_LABEL}, nên chưa thể gợi ý tạp chí. "
                "Bạn có thể gửi thêm abstract hoặc từ khóa để mình thử lại."
            )
            return MessageType.JOURNAL_LIST, summary, {
                "type": "journal_list",
                "data": [],
                "status": "insufficient_corpus",
                "doi_metadata": metadata,
            }

        topic_profile = ManuscriptTopicProfile.from_doi_metadata(metadata)
        manuscript_text = topic_profile.build_embedding_query()
        if len(manuscript_text.strip()) < 30:
            summary = (
                f"Mình chưa có đủ metadata mô tả nội dung bài báo trong {USER_SAFE_DATA_LABEL} để chạy journal matching. "
                "Bạn có thể gửi thêm abstract hoặc keywords."
            )
            return MessageType.JOURNAL_LIST, summary, {
                "type": "journal_list",
                "data": [],
                "status": "insufficient_corpus",
                "doi_metadata": metadata,
            }

        request = journal_match_service.create_match_request(
            db,
            current_user=current_user,
            payload=MatchRequestCreate(
                text=manuscript_text,
                title=metadata.get("title"),
                session_id=session_id,
                top_k=5,
                desired_venue_type="journal",
                include_cfps=False,
            ),
        )
        journal_match_service.run_request(db, current_user=current_user, request_id=request.id)
        result = journal_match_service.get_result(db, current_user=current_user, request_id=request.id)
        journals, summary = build_legacy_journal_payload(result)
        diagnostics = getattr(result.get("request"), "retrieval_diagnostics", None) or {}
        candidate_ids = [
            row.get("candidate_id") or row.get("venue_id")
            for row in journals
            if isinstance(row, dict) and (row.get("candidate_id") or row.get("venue_id"))
        ]
        match_status = diagnostics.get("match_status") or ("matched" if journals else "insufficient_corpus")
        return MessageType.JOURNAL_LIST, summary, {
            "type": "journal_list",
            "data": journals,
            "request_id": request.id,
            "candidate_ids": candidate_ids,
            "status": match_status,
            "doi_metadata": metadata,
        }

    def _run_general_qa_flow(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        user_message: str,
        pre_save_history: list[ChatMessage],
        user_ai_rule_phrases: list[str],
    ) -> tuple[MessageType, str, dict[str, Any] | None]:
        user_message_with_context = self._build_file_context(db, session_id, user_message)

        doi = self._extract_first_doi(user_message_with_context)
        exact_identifiers = citation_checker.extract_exact_identifiers(user_message_with_context)
        if doi:
            if self.JOURNAL_INTENT_PATTERN.search(user_message or ""):
                return self._run_journal_match_from_doi(
                    db,
                    current_user=current_user,
                    session_id=session_id,
                    doi=doi,
                )

            if self._is_doi_metadata_request(user_message):
                return self._run_doi_metadata_lookup(db, doi)

            if self.CITATION_VERIFY_PATTERN.search(user_message or ""):
                return self._run_mode_tool(
                    db,
                    current_user,
                    session_id,
                    SessionMode.VERIFICATION,
                    user_message_with_context,
                )

        if exact_identifiers:
            return self._run_mode_tool(
                db,
                current_user,
                session_id,
                SessionMode.VERIFICATION,
                user_message_with_context,
            )

        academic_query_result = None
        if not self._get_file_context(db, session_id) and academic_query_service.should_handle(user_message):
            academic_query_result = academic_query_service.answer(db, user_message)
        if academic_query_result is not None:
            return (
                MessageType.TEXT,
                academic_query_result.text,
                {
                    "type": "academic_lookup",
                    "status": "no_data" if not academic_query_result.records else "found",
                    "data": {
                        "records": academic_query_result.records,
                        "count": len(academic_query_result.records),
                    },
                },
            )

        if not academic_query_result:
            intent = self._classify_academic_intent(user_message)
            if intent == "general_academic_discussion":
                fc_response = gemini_service.generate_response(
                    history=pre_save_history,
                    user_text=user_message_with_context,
                    system_prompt_override=AIRA_GENERAL_ACADEMIC_PROMPT,
                    expose_tools=False,
                    user_ai_rule_phrases=user_ai_rule_phrases,
                )
                return MessageType.TEXT, fc_response.text, None

        fc_response = gemini_service.generate_response(
            history=pre_save_history,
            user_text=user_message_with_context,
            user_ai_rule_phrases=user_ai_rule_phrases,
        )
        try:
            msg_type = MessageType(fc_response.message_type)
        except (ValueError, KeyError):
            msg_type = MessageType.TEXT
        return msg_type, fc_response.text, fc_response.tool_results

    def _run_auto_mode_flow(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        user_message: str,
        pre_save_history: list[ChatMessage],
        user_ai_rule_phrases: list[str],
    ) -> tuple[MessageType, str, dict[str, Any]]:
        file_context = self._get_file_context(db, session_id)
        route = auto_intent_router.resolve(
            user_message,
            has_file_context=bool(file_context),
        )
        if route.is_ambiguous:
            return self._build_intent_disambiguation(route)

        tool_input = self._build_file_context(db, session_id, user_message)
        raw_user_doi = self._extract_first_doi(user_message)

        if route.resolved_feature == FEATURE_DOI_METADATA and raw_user_doi:
            return self._finalize_auto_response(route, *self._run_doi_metadata_lookup(db, raw_user_doi))

        if route.resolved_feature == FEATURE_JOURNAL_MATCH:
            if raw_user_doi:
                return self._finalize_auto_response(
                    route,
                    *self._run_journal_match_from_doi(
                        db,
                        current_user=current_user,
                        session_id=session_id,
                        doi=raw_user_doi,
                    ),
                )
            return self._finalize_auto_response(
                route,
                *self._run_mode_tool(db, current_user, session_id, SessionMode.JOURNAL_MATCH, tool_input),
            )

        if route.resolved_feature == FEATURE_VERIFICATION:
            return self._finalize_auto_response(
                route,
                *self._run_mode_tool(db, current_user, session_id, SessionMode.VERIFICATION, tool_input),
            )

        if route.resolved_feature == FEATURE_RETRACTION:
            return self._finalize_auto_response(
                route,
                *self._run_mode_tool(db, current_user, session_id, SessionMode.RETRACTION, tool_input),
            )

        if route.resolved_feature == FEATURE_AI_DETECTION:
            return self._finalize_auto_response(
                route,
                *self._run_mode_tool(db, current_user, session_id, SessionMode.AI_DETECTION, tool_input),
            )

        if route.resolved_feature == FEATURE_GRAMMAR:
            return self._finalize_auto_response(route, *self._run_grammar_tool(session_id, tool_input))

        general_msg_type, general_content, general_structured = self._run_general_qa_flow(
            db,
            current_user,
            session_id,
            user_message,
            pre_save_history,
            user_ai_rule_phrases,
        )
        return self._finalize_auto_response(
            route,
            general_msg_type,
            general_content,
            general_structured,
        )

    def complete_chat(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        user_message: str,
        mode_override: SessionMode | None = None,
    ) -> tuple[ChatMessage, ChatMessage, ChatSession]:
        session_obj = AccessGateway.assert_session_access(db, current_user, session_id)
        user_ai_rule_phrases = get_user_ai_detection_rule_phrases(current_user)

        if mode_override and mode_override != session_obj.mode:
            session_obj.mode = mode_override

        existing_user_message_count = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.USER,
            )
            .count()
        )
        should_generate_title = (
            existing_user_message_count == 0
            and self._is_default_title(session_obj.title, session_obj.mode)
        )

        db.add(session_obj)

        # ── Query history BEFORE saving (prevents current-msg duplication) ──
        pre_save_history = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(settings.chat_context_window)
            .all()
        )
        pre_save_history = list(reversed(pre_save_history))

        # ── Save user message ───────────────────────────────────────────────
        user_msg = self._save_message(
            db=db,
            session_id=session_id,
            role=MessageRole.USER,
            content=user_message,
            message_type=MessageType.TEXT,
        )

        if should_generate_title:
            session_obj.title = gemini_service.generate_chat_title(user_message, mode=session_obj.mode)
            db.add(session_obj)
            db.commit()
            db.refresh(session_obj)

        journal_followup = self._build_journal_followup_payload(db, session_id, user_message)
        if journal_followup is not None:
            content, structured = journal_followup
            assistant_msg = self._save_message(
                db=db,
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=content,
                message_type=MessageType.JOURNAL_LIST,
                tool_results=structured,
            )
            db.refresh(session_obj)
            return user_msg, assistant_msg, session_obj

        mode = session_obj.mode
        if mode == SessionMode.AUTO:
            msg_type, content, structured = self._run_auto_mode_flow(
                db,
                current_user,
                session_id,
                user_message,
                pre_save_history,
                user_ai_rule_phrases,
            )
            assistant_msg = self._save_message(
                db=db,
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=content,
                message_type=msg_type,
                tool_results=structured,
            )
            db.refresh(session_obj)
            return user_msg, assistant_msg, session_obj

        if mode in {
            SessionMode.VERIFICATION,
            SessionMode.JOURNAL_MATCH,
            SessionMode.RETRACTION,
            SessionMode.AI_DETECTION,
        }:
            # Inject file context so explicit tool modes also see the PDF text
            tool_input = self._build_file_context(db, session_id, user_message)
            if mode == SessionMode.VERIFICATION and self._is_doi_metadata_request(user_message):
                doi = self._extract_first_doi(tool_input)
                if doi:
                    msg_type, content, structured = self._run_doi_metadata_lookup(db, doi)
                    assistant_msg = self._save_message(
                        db=db,
                        session_id=session_id,
                        role=MessageRole.ASSISTANT,
                        content=content,
                        message_type=msg_type,
                        tool_results=structured,
                    )
                    db.refresh(session_obj)
                    return user_msg, assistant_msg, session_obj
            msg_type, content, structured = self._run_mode_tool(db, current_user, session_id, mode, tool_input)
            assistant_msg = self._save_message(
                db=db,
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=content,
                message_type=msg_type,
                tool_results=structured,
            )
            db.refresh(session_obj)
            return user_msg, assistant_msg, session_obj

        msg_type, content, structured = self._run_general_qa_flow(
            db,
            current_user,
            session_id,
            user_message,
            pre_save_history,
            user_ai_rule_phrases,
        )
        assistant_msg = self._save_message(
            db=db,
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=content,
            message_type=msg_type,
            tool_results=structured,
        )
        db.refresh(session_obj)
        return user_msg, assistant_msg, session_obj

    def log_file_upload(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        attachment: FileAttachment,
    ) -> ChatMessage:
        _ = AccessGateway.assert_session_access(db, current_user, session_id)
        payload = {
            "type": "file_upload",
            "data": {
                "attachment_id": attachment.id,
                "file_name": attachment.file_name,
                "mime_type": attachment.mime_type,
                "size_bytes": attachment.size_bytes,
                "storage_encrypted": attachment.storage_encrypted,
            },
        }
        content = f"Uploaded file: {attachment.file_name}"
        msg = self._save_message(
            db=db,
            session_id=session_id,
            role=MessageRole.SYSTEM,
            content=content,
            message_type=MessageType.FILE_UPLOAD,
            tool_results=payload,
        )
        return msg

    def persist_tool_interaction(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        user_input: str,
        message_type: MessageType,
        summary: str,
        tool_payload: dict[str, Any],
    ) -> tuple[ChatMessage, ChatMessage]:
        _ = AccessGateway.assert_session_access(db, current_user, session_id)
        user_msg = self._save_message(
            db=db,
            session_id=session_id,
            role=MessageRole.USER,
            content=user_input,
            message_type=MessageType.TEXT,
        )
        assistant_msg = self._save_message(
            db=db,
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=summary,
            message_type=message_type,
            tool_results=tool_payload,
        )
        return user_msg, assistant_msg


chat_service = ChatService()
