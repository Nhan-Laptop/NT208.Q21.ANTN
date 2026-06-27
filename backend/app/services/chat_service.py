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
from app.services.academic_policy import (
    AIRA_GENERAL_ACADEMIC_PROMPT,
    AIRA_RESOLVED_RECORD_FOLLOWUP_PROMPT,
    EXACT_RECORD_NOT_FOUND_MESSAGE,
    USER_SAFE_CORPUS_LABEL,
    USER_SAFE_DATA_LABEL,
    sanitize_user_payload,
    sanitize_user_text,
)
from app.services.external_academic_search import (
    AuthorPublicationLookupResult,
    ScholarlyLookupResult,
    external_academic_search_service,
)
from app.services.academic_verification_formatter import (
    format_citation_summary,
    format_retraction_summary,
)
from app.services.ai_detection_rule_service import get_runtime_rule_payloads
from app.services.ai_detection_service import ai_detection_service
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
from app.services.tools.citation import normalize_author_name
from app.services.tools.citation_batch_service import citation_batch_service
from app.services.tools.citation_checker import citation_checker
from app.services.tools.grammar_checker import grammar_checker
from app.services.tools.retraction_scan import retraction_scanner, scan_verified_retractions

try:
    from app.services.journal_match.service import (
        build_chat_journal_match_payload,
        build_legacy_journal_payload,
        journal_match_service,
    )
except Exception:  # pragma: no cover - optional heavy dependency path
    build_chat_journal_match_payload = None  # type: ignore[assignment]
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
        r"gợi\s*ý\s*tạp\s*chí|đề\s*xuất\s*tạp\s*chí|tạp\s*chí\s+phù\s*hợp|"
        r"tìm\s*tạp\s*chí|nên\s+gửi\s+bài\s+ở\s+đâu|nên\s+nộp\s+tạp\s+chí\s+nào|"
        r"journal\s+suggestion|journals?\s+suggestion|"
        r"journal\s+recommendation|journals?\s+recommendation|"
        r"journal\s+matching|journals?\s+matching|"
        r"recommend\s+journal|suggest\s+journal|"
        r"where\s+should\s+i\s+submit|"
        r"nơi\s*nộp\s*bài|journal\s+match|journals?\s+match|"
        r"suitable\s+journal|similar\s+manuscript|"
        r"nơi\s+đăng|gợi\s+ý\s+journal"
        r")\b",
        re.IGNORECASE,
    )
    _JOURNAL_INTENT_PREFIX_RE = re.compile(
        r"^(?:\s*(?:gợi\s*ý\s*tạp\s*chí\s*(?:cho)?\s*[:\-]?\s*"
        r"|đề\s*xuất\s*tạp\s*chí\s*(?:cho)?\s*[:\-]?\s*"
        r"|journal\s+recommendation\s+for\s*[:\-]?\s*"
        r"|journal\s+suggestion\s*[:\-]?\s*"
        r"|where\s+should\s+i\s+submit\s*[:\-]?\s*"
        r"|nên\s+nộp\s+tạp\s+chí\s+nào\s*[:\-]?\s*"
        r"|nên\s+gửi\s+bài\s+ở\s+đâu\s*[:\-]?\s*"
        r"))",
        re.IGNORECASE,
    )
    _VN_EN_LABEL_RE = re.compile(
        r"(?P<key>"
        r"title|tiêu\s*đề|tieu\s*de|"
        r"abstract|abstract|tóm\s*tắt|tom\s*tat|"
        r"keywords|from\s*keywords|từ\s*khóa|tu\s*khoa|"
        r"field|subjects?|lĩnh\s*vực|linh\s*vuc|chủ\s*đề|chu\s*de"
        r")\s*[:\-]?\s*(?P<value>.+)",
        re.IGNORECASE,
    )
    RECORD_FOLLOWUP_PATTERN = re.compile(
        r"\b("
        r"bài\s+này|bài\s+báo\s+này|paper\s+này|article\s+này|tài\s+liệu\s+này|"
        r"công\s+trình\s+này|nghiên\s+cứu\s+này|this\s+paper|this\s+article|that\s+paper"
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
        r"analyze|phân\s*tích|provide|show|extract|list|authors?|tác\s*giả|tac\s*gia|"
        r"thông\s*tin\s+về|thong\s*tin\s+ve|information\s+about|"
        r"doi\s+info|doi\s+metadata|metadata\s+doi|metadata|paper\s+info|"
        r"abstract|summary"
        r")\b",
        re.IGNORECASE,
    )
    AUTHOR_QUERY_PATTERN = re.compile(
        r"\b(tác\s*giả|tac\s*gia|authors?)\b",
        re.IGNORECASE,
    )
    AUTHOR_PUBLICATION_PATTERN = re.compile(
        r"\b("
        r"publication(?:s)?|paper(?:s)?|works?|"
        r"bài\s*báo\s+khác|bai\s*bao\s*khac|"
        r"công\s*bố|cong\s*bo|công\s*trình|cong\s*trinh|"
        r"other\s+papers?|related\s+works?"
        r")\b",
        re.IGNORECASE,
    )
    AUTHOR_PUBLICATION_NAME_PATTERNS = (
        re.compile(
            r"\b(?:publication(?:s)?|paper(?:s)?|works?|bài\s*báo(?:\s+khác)?|bai\s*bao(?:\s*khac)?|"
            r"công\s*trình(?:\s+khác)?|cong\s*trinh(?:\s*khac)?|công\s*bố|cong\s*bo)\b"
            r"(?:[^\n]{0,40}?)\b(?:của|cua|for|by)\s+(?P<name>[^\n]+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?P<name>.+?)\s+(?:có|co|has|have)\s+"
            r"(?:những|nhung|các|cac|all|bao\s+nhieu|bao\s+nhiêu|what|which)?\s*"
            r"(?:publication(?:s)?|paper(?:s)?|works?|bài\s*báo|bai\s*bao|công\s*trình|cong\s*trinh)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:tất\s*cả|tat\s*ca|all)\b(?:[^\n]{0,30}?)"
            r"\b(?:publication(?:s)?|paper(?:s)?|works?|bài\s*báo|bai\s*bao|công\s*trình|cong\s*trinh)\b"
            r"(?:[^\n]{0,30}?)\b(?:mà|ma|by)\s+(?P<name>.+?)\s+"
            r"(?:là\s+tác\s*giả|la\s*tac\s*gia|authored|author)\b",
            re.IGNORECASE,
        ),
    )
    DOI_INFO_PATTERN = re.compile(
        r"\b("
        r"thông\s*tin\s*về|thong\s*tin\s+ve|information\s+about|doi\s+info|"
        r"doi\s+metadata|metadata\s+doi|paper\s+info|bài\s+báo\s+về|"
        r"analyze|phân\s*tích|provide|authors?|tác\s*giả|tac\s*gia|title|journal|publisher|"
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
        re.compile(r"\bauthors?\b", re.IGNORECASE),
        re.compile(r"\btác\s*giả\b", re.IGNORECASE),
        re.compile(r"\blĩnh\s*vực\b", re.IGNORECASE),
        re.compile(r"\bchủ\s*đề\b", re.IGNORECASE),
        re.compile(r"\btạp\s*chí\b", re.IGNORECASE),
        re.compile(r"\bnăm\s*xuất\s*bản\b", re.IGNORECASE),
    )
    DOI_REQUESTED_FIELD_PATTERNS = (
        ("authors", re.compile(
            r"\b("
            r"tác\s*giả|tac\s*gia|authors?|"
            r"ai\s*viết|ai\s*viet|người\s*viết|nguoi\s*viet|"
            r"nhóm\s*tác\s*giả|nhom\s*tac\s*gia"
            r")\b",
            re.IGNORECASE,
        )),
        ("title", re.compile(
            r"\b(title|tiêu\s*đề|tieu\s*de|tên\s*bài|ten\s*bai|tên\s*bài\s*báo|ten\s*bai\s*bao)\b",
            re.IGNORECASE,
        )),
        ("journal", re.compile(
            r"\b(journal|tạp\s*chí|tap\s*chi|published\s+in|đăng\s+ở\s+đâu|dang\s+o\s+dau)\b",
            re.IGNORECASE,
        )),
        ("publisher", re.compile(
            r"\b(publisher|nhà\s*xuất\s*bản|nha\s*xuat\s*ban)\b",
            re.IGNORECASE,
        )),
        ("publication_year", re.compile(
            r"\b(publication\s*year|published\s*year|năm\s*xuất\s*bản|nam\s*xuat\s*ban|năm\s*nào|nam\s*nao)\b",
            re.IGNORECASE,
        )),
        ("research_field", re.compile(
            r"\b(research\s*field|lĩnh\s*vực|linh\s*vuc|field\s+of\s+research)\b",
            re.IGNORECASE,
        )),
        ("main_topic", re.compile(
            r"\b(main\s*topic|chủ\s*đề|chu\s*de|topic)\b",
            re.IGNORECASE,
        )),
        ("abstract", re.compile(
            r"\b(abstract|summary|tóm\s*tắt|tom\s*tat)\b",
            re.IGNORECASE,
        )),
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
                ChatMessage.message_type.in_([MessageType.JOURNAL_LIST, MessageType.TEXT]),
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
        payload_type = previous.tool_results.get("type")
        if payload_type not in ("journal_list", "journal_match"):
            return None
        if payload_type == "journal_list":
            rows = previous.tool_results.get("data")
        else:
            rows = previous.tool_results.get("matches")
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
            subject_fit = row.get("subject_fit")
            domain_text = ""
            if domains:
                domain_text = f" Chủ đề ghi nhận: {', '.join(str(item) for item in domains[:4])}."
            elif subject_fit:
                domain_text = f" Phù hợp: {subject_fit}."
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

    @staticmethod
    def _resolved_record_from_doi_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
        title = str(metadata.get("title") or "").strip()
        if not title:
            return None
        return {
            "title": title,
            "authors": list(metadata.get("authors") or []),
            "year": metadata.get("publication_year") or metadata.get("year"),
            "venue": metadata.get("journal") or metadata.get("venue"),
            "doi": metadata.get("doi"),
            "abstract": metadata.get("abstract"),
            "url": metadata.get("url"),
            "source": metadata.get("source"),
            "confidence": metadata.get("confidence"),
            "match_status": metadata.get("verification_status") or "verified",
            "subjects": list(metadata.get("subjects") or []),
            "keywords": list(metadata.get("keywords") or []),
        }

    @classmethod
    def _extract_resolved_record(cls, tool_results: dict[str, Any] | list[Any] | None) -> dict[str, Any] | None:
        if not isinstance(tool_results, dict):
            return None

        payload_type = str(tool_results.get("type") or "").strip().lower()
        if payload_type == "academic_lookup":
            data = tool_results.get("data")
            if isinstance(data, dict):
                best_record = data.get("best_record")
                if isinstance(best_record, dict) and best_record.get("title"):
                    return best_record
            return None

        if payload_type in ("journal_list", "journal_match"):
            source_record = tool_results.get("source_record")
            if isinstance(source_record, dict) and source_record.get("title"):
                return source_record
            doi_metadata = tool_results.get("doi_metadata")
            if isinstance(doi_metadata, dict):
                return cls._resolved_record_from_doi_metadata(doi_metadata)
            source_fields = tool_results.get("source_fields")
            if isinstance(source_fields, dict) and source_fields.get("title"):
                return {"title": source_fields["title"], "abstract": source_fields.get("abstract"), "keywords": source_fields.get("keywords")}
            return None

        if payload_type == "doi_metadata":
            data = tool_results.get("data")
            if isinstance(data, dict):
                return cls._resolved_record_from_doi_metadata(data)
        if payload_type == "author_publication_search":
            source_record = tool_results.get("source_record")
            if isinstance(source_record, dict) and source_record.get("title"):
                return source_record
        return None

    def _latest_resolved_record(self, db: Session, session_id: str) -> dict[str, Any] | None:
        messages = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.ASSISTANT,
            )
            .order_by(desc(ChatMessage.created_at))
            .limit(12)
            .all()
        )
        for message in messages:
            record = self._extract_resolved_record(message.tool_results)
            if record is not None:
                return record
        return None

    def _should_reuse_latest_record(
        self,
        text: str,
        latest_record: dict[str, Any] | None,
        *,
        journal_intent: bool = False,
    ) -> bool:
        if not latest_record or not latest_record.get("title"):
            return False
        normalized = (text or "").strip()
        if not normalized or len(normalized) > 160:
            return False
        if self._extract_first_doi(normalized) or citation_checker.extract_exact_identifiers(normalized):
            return False
        if journal_intent:
            return bool(self.RECORD_FOLLOWUP_PATTERN.search(normalized) or not external_academic_search_service.should_handle(normalized))
        return bool(self.RECORD_FOLLOWUP_PATTERN.search(normalized))

    @staticmethod
    def _build_resolved_record_block(record: dict[str, Any]) -> str:
        authors = record.get("authors") if isinstance(record.get("authors"), list) else []
        subjects = record.get("subjects") if isinstance(record.get("subjects"), list) else []
        keywords = record.get("keywords") if isinstance(record.get("keywords"), list) else []
        parts = [
            f"Title: {record.get('title')}",
            f"Authors: {', '.join(str(author) for author in authors[:8])}" if authors else None,
            f"Year: {record.get('year')}" if record.get("year") else None,
            f"Venue: {record.get('venue')}" if record.get("venue") else None,
            f"DOI: {record.get('doi')}" if record.get("doi") else None,
            f"Source: {record.get('source')}" if record.get("source") else None,
            f"Confidence: {record.get('confidence')}" if record.get("confidence") is not None else None,
            f"Subjects: {', '.join(str(item) for item in subjects[:6])}" if subjects else None,
            f"Keywords: {', '.join(str(item) for item in keywords[:8])}" if keywords else None,
            f"Abstract: {record.get('abstract')}" if record.get("abstract") else None,
            f"URL: {record.get('url')}" if record.get("url") else None,
        ]
        body = "\n".join(str(part).strip() for part in parts if part)
        return f"<Resolved_Scholarly_Record>\n{body}\n</Resolved_Scholarly_Record>"

    def _run_record_followup_qa(
        self,
        user_message: str,
        pre_save_history: list[ChatMessage],
        latest_record: dict[str, Any],
        user_ai_rule_phrases: list[str],
        user_ai_runtime_rules: list[dict[str, Any]],
    ) -> tuple[MessageType, str, None]:
        fc_response = gemini_service.generate_response(
            history=pre_save_history,
            user_text=f"{user_message}\n\n{self._build_resolved_record_block(latest_record)}",
            system_prompt_override=AIRA_RESOLVED_RECORD_FOLLOWUP_PROMPT,
            expose_tools=False,
            user_ai_rule_phrases=user_ai_rule_phrases,
            user_ai_runtime_rules=user_ai_runtime_rules,
        )
        return MessageType.TEXT, fc_response.text, None

    @staticmethod
    def _checked_source_names(checked_sources: list[dict[str, Any]] | None) -> str:
        names = [
            str(source.get("name"))
            for source in (checked_sources or [])
            if isinstance(source, dict) and source.get("name")
        ]
        deduped: list[str] = []
        seen: set[str] = set()
        for name in names:
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(name)
        return ", ".join(deduped)

    @classmethod
    def _lookup_checked_source_names(cls, result: ScholarlyLookupResult) -> str:
        return cls._checked_source_names(result.checked_sources)

    @classmethod
    def _build_academic_lookup_field_response(
        cls,
        field: str,
        lookup_result: ScholarlyLookupResult,
    ) -> str | None:
        if field != "authors":
            return None

        best_record = lookup_result.best_record
        if not best_record:
            return None

        title = str(best_record.get("title") or "").strip()
        authors = best_record.get("authors") or []
        if not authors:
            return None

        lines = [f"Các tác giả được tìm thấy cho bài \"{title}\" là:", "", cls._format_numbered_text_list(authors), ""]

        sources = cls._checked_source_names(lookup_result.checked_sources)
        if sources:
            lines.append(f"Nguồn: {sources}")

        confidence_text = f"Độ tin cậy: {lookup_result.confidence_label or 'Thấp'}"
        if lookup_result.status == "external_possible_match":
            confidence_text += " (kết quả tạm thời, metadata giữa các nguồn có thể không đồng nhất)"
        elif lookup_result.status == "low_confidence":
            confidence_text += " (dưới ngưỡng xác minh)"
        lines.append(confidence_text)

        if lookup_result.status in {"external_possible_match", "low_confidence"}:
            lines.append("")
            lines.append("Bạn có thể cung cấp DOI hoặc link paper để xác minh chính xác hơn.")

        return "\n".join(lines)

    def _build_academic_lookup_summary(self, result: ScholarlyLookupResult) -> str:
        source_text = self._lookup_checked_source_names(result)
        if result.status == "internal_found":
            return (
                f"Mình tìm thấy {len(result.records)} bản ghi liên quan trong {USER_SAFE_DATA_LABEL}. "
                "Xem metadata, bằng chứng và mức độ khớp ở thẻ kết quả bên dưới."
            )
        if result.status == "external_found":
            return (
                f"Mình không tìm thấy mục này trong {USER_SAFE_DATA_LABEL}, nhưng đã kiểm tra các nguồn học thuật bên ngoài "
                f"({source_text}) và tìm được một bản ghi phù hợp. Xem metadata, nguồn kiểm tra và confidence ở thẻ bên dưới."
            )
        if result.status == "external_possible_match":
            return (
                f"Mình không tìm thấy bản ghi đủ mạnh trong {USER_SAFE_DATA_LABEL}, nhưng đã tìm được một ứng viên bên ngoài có mức khớp trung bình "
                f"sau khi kiểm tra {source_text}. Bạn nên xem confidence và nguồn kiểm tra trước khi dùng kết quả này."
            )
        if result.status == "low_confidence":
            return (
                f"Mình đã kiểm tra {USER_SAFE_DATA_LABEL} và các nguồn học thuật bên ngoài ({source_text}), "
                "nhưng candidate gần nhất vẫn dưới ngưỡng xác minh nên mình không promote nó thành kết quả chính."
            )
        if result.status == "source_degraded":
            base = (
                f"Mình đã kiểm tra {USER_SAFE_DATA_LABEL} và các nguồn học thuật bên ngoài ({source_text}), "
                "nhưng một hoặc nhiều nguồn ngoài bị lỗi hoặc timeout nên hiện chưa thể kết luận chắc chắn."
            )
            if result.source_health == "degraded" and not result.best_record:
                base += " External search bị degrade và không có candidate đủ tin cậy để hiển thị."
            return base
        if result.status == "no_reliable_match":
            parts: list[str] = [
                f"Mình đã kiểm tra {USER_SAFE_DATA_LABEL} và các nguồn học thuật bên ngoài ({source_text}), "
                "nhưng không tìm thấy kết quả nào vượt qua ngưỡng đối sánh với thông tin bạn cung cấp."
            ]
            input_ref = result.input_reference or {}
            if input_ref.get("authors"):
                parts.append(f"Tác giả bạn cung cấp: {', '.join(input_ref['authors'][:4])}.")
            if input_ref.get("venue"):
                parts.append(f"Venue: {input_ref['venue']}.")
            if input_ref.get("year"):
                parts.append(f"Năm: {input_ref['year']}.")
            result_notes = list(result.notes or [])
            if result.source_health == "degraded":
                parts.append("Một số nguồn học thuật bên ngoài bị degrade nên kết quả có thể chưa đầy đủ.")
                degraded_notes = [n for n in result_notes if "degrad" in n.lower()]
                if degraded_notes:
                    parts.extend(degraded_notes[:2])
            return " ".join(parts)
        return (
            f"Mình đã kiểm tra {USER_SAFE_DATA_LABEL} và các nguồn học thuật bên ngoài ({source_text}), "
            "nhưng chưa tìm thấy bản ghi đủ tin cậy. Thẻ kết quả bên dưới cho biết các nguồn đã kiểm tra."
        )

    @staticmethod
    def _build_academic_lookup_payload(result: ScholarlyLookupResult) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "academic_lookup",
            "status": result.status,
            "source_mode": result.source_mode,
            "confidence": result.confidence,
            "confidence_label": result.confidence_label,
            "external_search_used": result.external_search_used,
            "checked_sources": result.checked_sources,
            "source_diagnostics": result.source_diagnostics,
            "query_terms": result.query_terms,
            "source_health": result.source_health,
            "input_reference": result.input_reference,
            "rejected_candidates": result.rejected_candidates,
            "data": {
                "records": result.records,
                "count": len(result.records),
                "best_record": result.best_record,
                "low_confidence_records": result.low_confidence_records,
                "notes": result.notes,
                "internal_result": result.internal_result,
            },
        }
        return payload

    def _run_academic_lookup_flow(
        self,
        db: Session,
        user_message: str,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        lookup_result = external_academic_search_service.lookup(db, user_message)
        requested_field = self.detect_requested_metadata_field(user_message)
        text = self._build_academic_lookup_field_response(requested_field, lookup_result)
        if not text:
            text = self._build_academic_lookup_summary(lookup_result)
        payload = self._build_academic_lookup_payload(lookup_result)
        if requested_field:
            payload["requested_field"] = requested_field
        return (
            MessageType.TEXT,
            text,
            payload,
        )

    def _run_journal_match_from_resolved_record(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        record: dict[str, Any],
        *,
        lookup_result: ScholarlyLookupResult | None = None,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        if journal_match_service is None or build_legacy_journal_payload is None:
            return MessageType.TEXT, (
                "Tính năng gợi ý tạp chí hiện chưa sẵn sàng trong môi trường này. "
                "Bạn vui lòng thử lại sau."
            ), {"type": "text", "error": "journal_match_service_unavailable"}

        metadata = {
            "title": record.get("title"),
            "abstract": record.get("abstract"),
            "keywords": list(record.get("keywords") or []),
            "subjects": list(record.get("subjects") or []),
        }
        topic_profile = ManuscriptTopicProfile.from_doi_metadata(metadata)
        manuscript_text = topic_profile.build_embedding_query()
        if len(manuscript_text.strip()) < 30:
            summary = (
                "Mình đã resolve được tài liệu này từ nguồn học thuật, nhưng metadata hiện chưa đủ dày "
                "để chạy journal matching đáng tin cậy. Cần thêm abstract hoặc keywords cụ thể hơn."
            )
            payload = {
                "type": "journal_list",
                "data": [],
                "status": "insufficient_record_metadata",
                "source_record": record,
            }
            if lookup_result is not None:
                payload["checked_sources"] = lookup_result.checked_sources
                payload["source_diagnostics"] = lookup_result.source_diagnostics
            return MessageType.JOURNAL_LIST, summary, payload

        request = journal_match_service.create_match_request(
            db,
            current_user=current_user,
            payload=MatchRequestCreate(
                text=manuscript_text,
                title=record.get("title"),
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
        payload: dict[str, Any] = {
            "type": "journal_list",
            "data": journals,
            "request_id": request.id,
            "candidate_ids": candidate_ids,
            "status": diagnostics.get("match_status") or ("matched" if journals else "insufficient_corpus"),
            "source_record": record,
        }
        if lookup_result is not None:
            payload["checked_sources"] = lookup_result.checked_sources
            payload["source_diagnostics"] = lookup_result.source_diagnostics
        return MessageType.JOURNAL_LIST, summary, payload

    def _build_journal_record_lookup_failure(
        self,
        lookup_result: ScholarlyLookupResult,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        if lookup_result.status in ("no_reliable_match", "source_degraded"):
            status = "source_degraded" if lookup_result.status == "source_degraded" else "record_not_found"
            if status == "source_degraded":
                summary = (
                    "Mình chưa thể gợi ý tạp chí vì bước resolve tài liệu từ nguồn học thuật bên ngoài đang bị degrade "
                    "hoặc timeout. Bạn có thể thử lại sau hoặc gửi thêm DOI/abstract."
                )
            else:
                summary = (
                    "Mình chưa resolve được một bản ghi học thuật đủ tin cậy cho tài liệu này, "
                    "nên chưa chạy journal matching để tránh gợi ý sai lĩnh vực."
                )
        else:
            status = "record_not_found"
            summary = (
                "Mình chưa resolve được một bản ghi học thuật đủ tin cậy cho tài liệu này, "
                "nên chưa chạy journal matching để tránh gợi ý sai lĩnh vực."
            )
        return MessageType.JOURNAL_LIST, summary, {
            "type": "journal_list",
            "data": [],
            "status": status,
            "checked_sources": lookup_result.checked_sources,
            "source_diagnostics": lookup_result.source_diagnostics,
        }

    def _run_journal_match_from_lookup_text(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        user_message: str,
        latest_record: dict[str, Any] | None = None,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        if latest_record is not None and self._should_reuse_latest_record(user_message, latest_record, journal_intent=True):
            return self._run_journal_match_from_resolved_record(
                db,
                current_user=current_user,
                session_id=session_id,
                record=latest_record,
            )

        lookup_result = external_academic_search_service.lookup(db, user_message)
        if lookup_result.best_record and lookup_result.status in {"internal_found", "external_found"}:
            return self._run_journal_match_from_resolved_record(
                db,
                current_user=current_user,
                session_id=session_id,
                record=lookup_result.best_record,
                lookup_result=lookup_result,
            )
        return self._build_journal_record_lookup_failure(lookup_result)

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
                report = citation_batch_service.verify_text(text)
                return MessageType.CITATION_REPORT, report["text"], report
            except Exception as exc:
                logger.exception("VERIFICATION mode failed for session %s", session_id)
                return MessageType.TEXT, (
                    "Mình chưa xác minh được trích dẫn cho nội dung này. "
                    "Bạn có thể thử lại hoặc gửi DOI/trích dẫn cụ thể hơn."
                ), {"type": "text", "error": str(exc)}

        if mode == SessionMode.JOURNAL_MATCH:
            if journal_match_service is None or build_chat_journal_match_payload is None:
                return MessageType.TEXT, (
                    "Tính năng gợi ý tạp chí hiện chưa sẵn sàng trong môi trường này. "
                    "Bạn vui lòng thử lại sau."
                ), {"type": "text", "error": "journal_match_service_unavailable"}
            manuscript_fields = self._extract_manuscript_fields_from_text(text)
            canonical = manuscript_fields.get("_canonical_text", text)
            if len(canonical.strip()) < 30:
                return (
                    MessageType.TEXT,
                    "Mình cần thêm nội dung mô tả (abstract, keywords, lĩnh vực) để gợi ý tạp chí.",
                    {"type": "journal_match", "matches": [], "status": "insufficient_manuscript_content"},
                )
            try:
                request = journal_match_service.create_match_request(
                    db,
                    current_user=current_user,
                    payload=MatchRequestCreate(
                        text=canonical,
                        title=manuscript_fields.get("title"),
                        session_id=session_id,
                        top_k=5,
                        desired_venue_type="journal",
                        include_cfps=False,
                    ),
                )
                journal_match_service.run_request(db, current_user=current_user, request_id=request.id)
                result = journal_match_service.get_result(db, current_user=current_user, request_id=request.id)
                _matches, summary, payload = build_chat_journal_match_payload(result)
                source_fields = {k: v for k, v in manuscript_fields.items() if not k.startswith("_") and v}
                payload["source_fields"] = source_fields
                return MessageType.TEXT, summary, payload
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
                runtime_rules = get_runtime_rule_payloads(
                    db,
                    current_user,
                    use_custom_rules=True,
                )
                result = ai_detection_service.analyze_text(
                    text,
                    mode="deep",
                    use_custom_rules=True,
                    runtime_rule_payloads=runtime_rules,
                    include_explanation=True,
                )
                summary = ai_detection_service.build_summary_text(result)
                return MessageType.AI_WRITING_DETECTION, summary, ai_detection_service.build_tool_payload(result)
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
        if isinstance(tool_results, dict) and tool_results.get("type") == "journal_match":
            return FEATURE_JOURNAL_MATCH
        if message_type == MessageType.TEXT and isinstance(tool_results, dict) and tool_results.get("type") == "journal_match":
            return FEATURE_JOURNAL_MATCH
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

    @staticmethod
    def _normalize_orcid(value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        text = re.sub(r"^https?://orcid\.org/", "", text, flags=re.IGNORECASE).strip().strip("/")
        return text or None

    @staticmethod
    def _normalized_author_key(name: str | None) -> str:
        tokens = [token for token in normalize_author_name(str(name or "")).split() if token]
        if not tokens:
            return ""
        if len(tokens) == 1:
            return tokens[0]
        return " ".join(sorted(tokens))

    @classmethod
    def _author_name_matches(cls, candidate_name: str | None, target_name: str | None) -> bool:
        candidate_key = cls._normalized_author_key(candidate_name)
        target_key = cls._normalized_author_key(target_name)
        if not candidate_key or not target_key:
            return False
        if candidate_key == target_key:
            return True
        candidate_tokens = candidate_key.split()
        target_tokens = target_key.split()
        if len(candidate_tokens) >= 2 and len(target_tokens) >= 2:
            return candidate_tokens[0] == target_tokens[0] and candidate_tokens[-1] == target_tokens[-1]
        return False

    @classmethod
    def _clean_author_query_name(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        text = re.sub(r"^[\"'“”‘’\s]+|[\"'“”‘’\s]+$", "", text)
        text = re.sub(r"^(?:tác\s*giả|tac\s*gia|author)\s+(?:là|la|named)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+(?:nữa\s+không|nua\s+khong|có\s+không|co\s+khong|không|khong)\s*$", "", text, flags=re.IGNORECASE)
        text = text.strip(" \t\r\n.,;:!?()[]{}")
        return text or None

    @classmethod
    def _is_likely_author_name(cls, value: str | None) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if cls.RECORD_FOLLOWUP_PATTERN.search(text):
            return False
        tokens = [token for token in normalize_author_name(text).split() if token]
        if len(tokens) < 2 or len(tokens) > 8:
            return False
        banned = {
            "publication", "publications", "paper", "papers", "work", "works",
            "bai", "bao", "cong", "trinh", "doi", "author", "authors",
            "tac", "gia", "this", "that",
        }
        if any(token in banned for token in tokens):
            return False
        return sum(1 for token in tokens if any(char.isalpha() for char in token)) >= 2

    @classmethod
    def _extract_author_name_from_query(cls, text: str) -> str | None:
        normalized = (text or "").strip()
        if not normalized:
            return None
        for pattern in cls.AUTHOR_PUBLICATION_NAME_PATTERNS:
            match = pattern.search(normalized)
            if not match:
                continue
            candidate = cls._clean_author_query_name(match.group("name"))
            if candidate and cls._is_likely_author_name(candidate):
                return candidate
        return None

    @staticmethod
    def _requests_other_publications(text: str) -> bool:
        return bool(re.search(r"\b(khác|khac|other)\b", text or "", flags=re.IGNORECASE))

    def _recent_assistant_messages(
        self,
        db: Session,
        session_id: str,
        *,
        limit: int = 12,
    ) -> list[ChatMessage]:
        return (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.ASSISTANT,
            )
            .order_by(desc(ChatMessage.created_at))
            .limit(limit)
            .all()
        )

    def _resolve_author_context_from_history(
        self,
        db: Session,
        session_id: str,
        author_name: str | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
        for message in self._recent_assistant_messages(db, session_id):
            tool_results = message.tool_results if isinstance(message.tool_results, dict) else {}
            payload_type = str(tool_results.get("type") or "").strip().lower()

            if payload_type == "author_publication_search":
                source_record = tool_results.get("source_record") if isinstance(tool_results.get("source_record"), dict) else None
                authors_payload = tool_results.get("authors") if isinstance(tool_results.get("authors"), list) else []
                for author in authors_payload:
                    if not isinstance(author, dict):
                        continue
                    candidate_name = str(author.get("name") or "").strip()
                    if author_name and not self._author_name_matches(candidate_name, author_name):
                        continue
                    openalex_id = (
                        author.get("openalex_id")
                        or ((author.get("external_ids") or {}).get("openalex") if isinstance(author.get("external_ids"), dict) else None)
                    )
                    return ({
                        "name": candidate_name,
                        "orcid": author.get("orcid"),
                        "openalex_id": openalex_id,
                        "external_ids": {"openalex": openalex_id} if openalex_id else {},
                        "confidence": author.get("confidence") or 0.98,
                        "notes": list(author.get("notes") or []),
                    }, source_record, True)

            if payload_type == "doi_metadata":
                data = tool_results.get("data")
                if not isinstance(data, dict):
                    continue
                source_record = self._resolved_record_from_doi_metadata(data)
                authors_payload = data.get("authors") if isinstance(data.get("authors"), list) else []
                for candidate_name in authors_payload:
                    if not author_name or self._author_name_matches(str(candidate_name or ""), author_name):
                        return ({
                            "name": str(candidate_name or "").strip(),
                            "confidence": 0.92,
                            "notes": [],
                        }, source_record, True)

            record = self._extract_resolved_record(tool_results)
            authors = record.get("authors") if isinstance(record, dict) and isinstance(record.get("authors"), list) else []
            if author_name:
                for candidate_name in authors:
                    if self._author_name_matches(str(candidate_name or ""), author_name):
                        return ({
                            "name": str(candidate_name or "").strip(),
                            "confidence": 0.88,
                            "notes": [],
                        }, record, True)
            elif len(authors) == 1:
                return ({
                    "name": str(authors[0] or "").strip(),
                    "confidence": 0.88,
                    "notes": [],
                }, record, True)

        return None, None, False

    def _is_author_publication_request(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized:
            return False
        has_doi = bool(self._extract_first_doi(normalized))
        has_author_signal = bool(self.AUTHOR_QUERY_PATTERN.search(normalized))
        has_publication_signal = bool(self.AUTHOR_PUBLICATION_PATTERN.search(normalized))
        has_record_signal = bool(self.RECORD_FOLLOWUP_PATTERN.search(normalized))
        has_named_author = bool(self._extract_author_name_from_query(normalized))
        return bool(
            (has_doi and has_author_signal and has_publication_signal)
            or has_named_author
            or (has_publication_signal and (has_author_signal or has_record_signal))
        )

    def _resolve_doi_author_context(
        self,
        db: Session,
        doi: str,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        normalized = citation_checker.normalize_doi(doi)
        metadata, status = self._resolve_doi_metadata(db, normalized)
        source_record = self._resolved_record_from_doi_metadata(metadata) if status == "verified" else None

        authors_by_key: dict[str, dict[str, Any]] = {}
        notes: list[str] = []
        checked_sources: list[dict[str, Any]] = []

        def merge_author(payload: dict[str, Any]) -> None:
            name = str(payload.get("name") or "").strip()
            if not name:
                return
            orcid = self._normalize_orcid(payload.get("orcid"))
            openalex_id = str(payload.get("openalex_id") or "").strip() or None
            key = (
                f"orcid:{orcid.lower()}" if orcid else
                f"openalex:{openalex_id.lower()}" if openalex_id else
                f"name:{self._normalized_author_key(name)}"
            )
            if not key or key.endswith(":"):
                return
            existing = authors_by_key.get(key)
            entry = {
                "name": name,
                "orcid": orcid,
                "openalex_id": openalex_id,
                "affiliation": payload.get("affiliation"),
                "author_order": payload.get("author_order"),
                "confidence": float(payload.get("confidence") or 0.0),
                "notes": self._dedupe_text_list(payload.get("notes") or []),
            }
            if existing is None:
                authors_by_key[key] = entry
                return
            if not existing.get("orcid") and entry.get("orcid"):
                existing["orcid"] = entry["orcid"]
            if not existing.get("openalex_id") and entry.get("openalex_id"):
                existing["openalex_id"] = entry["openalex_id"]
            if not existing.get("affiliation") and entry.get("affiliation"):
                existing["affiliation"] = entry["affiliation"]
            if existing.get("author_order") is None and entry.get("author_order") is not None:
                existing["author_order"] = entry["author_order"]
            existing["confidence"] = max(float(existing.get("confidence") or 0.0), float(entry.get("confidence") or 0.0))
            existing["notes"] = self._dedupe_text_list([*(existing.get("notes") or []), *(entry.get("notes") or [])])

        article = (
            db.query(Article)
            .options(selectinload(Article.authors), selectinload(Article.venue))
            .filter(func.lower(Article.doi) == normalized)
            .first()
        )
        if article is not None:
            checked_sources.append(
                external_academic_search_service._checked_source(
                    "internal",
                    "matched",
                    detail="Resolved source paper and authors from the internal academic database.",
                    candidate_count=1,
                )
            )
            for author in sorted(article.authors, key=lambda item: item.author_order if item.author_order is not None else 9999):
                merge_author(
                    {
                        "name": author.full_name,
                        "orcid": author.orcid,
                        "affiliation": author.affiliation,
                        "author_order": author.author_order,
                        "confidence": 1.0,
                    }
                )
        else:
            checked_sources.append(
                external_academic_search_service._checked_source(
                    "internal",
                    "no_match",
                    detail="The DOI was not present in the internal academic database; falling back to external scholarly metadata.",
                    candidate_count=0,
                )
            )

        exact_result = citation_checker.verify_doi_exact(normalized, citation_context={"raw": normalized})
        if isinstance(exact_result.source_diagnostics, dict) and exact_result.source_diagnostics:
            checked_sources = external_academic_search_service._merge_checked_sources(
                checked_sources,
                external_academic_search_service._checked_sources_from_diagnostics(exact_result.source_diagnostics),
            )

        if exact_result.status == "DOI_VERIFIED":
            meta = exact_result.metadata or {}
            crossref = meta.get("crossref") if isinstance(meta.get("crossref"), dict) else {}
            openalex = meta.get("openalex") if isinstance(meta.get("openalex"), dict) else {}
            if not openalex:
                try:
                    openalex_result = citation_checker._verify_doi_openalex_exact(normalized)
                    if openalex_result and isinstance(openalex_result.metadata, dict):
                        openalex = openalex_result.metadata.get("openalex") or {}
                except Exception:
                    logger.debug("OpenAlex author enrichment failed for DOI %s", normalized, exc_info=True)

            for index, author in enumerate(crossref.get("author", []) or []):
                if not isinstance(author, dict):
                    continue
                given = str(author.get("given") or "").strip()
                family = str(author.get("family") or "").strip()
                name = " ".join(part for part in [given, family] if part).strip()
                if not name:
                    continue
                merge_author(
                    {
                        "name": name,
                        "orcid": author.get("ORCID") or author.get("orcid"),
                        "author_order": index,
                        "confidence": 0.9,
                    }
                )

            for index, authorship in enumerate(openalex.get("authorships", []) or []):
                if not isinstance(authorship, dict):
                    continue
                author = authorship.get("author") or {}
                if not isinstance(author, dict):
                    continue
                name = str(author.get("display_name") or "").strip()
                if not name:
                    continue
                institutions = authorship.get("institutions") or []
                affiliation = "; ".join(
                    str(item.get("display_name")).strip()
                    for item in institutions
                    if isinstance(item, dict) and str(item.get("display_name") or "").strip()
                ) or None
                merge_author(
                    {
                        "name": name,
                        "orcid": author.get("orcid"),
                        "openalex_id": author.get("id"),
                        "affiliation": affiliation,
                        "author_order": index,
                        "confidence": 0.98,
                    }
                )

        authors = sorted(
            authors_by_key.values(),
            key=lambda item: (item.get("author_order") is None, item.get("author_order") if item.get("author_order") is not None else 9999, item.get("name") or ""),
        )
        if source_record is not None and authors:
            source_record["authors"] = [str(author.get("name")) for author in authors if author.get("name")]
        if source_record is None:
            notes.append("The DOI could not be resolved into a source paper, so author publication lookup could not continue.")
        return source_record, authors, checked_sources, self._dedupe_text_list(notes)

    def _is_doi_metadata_request(self, text: str) -> bool:
        normalized = (text or "").strip()
        if not normalized or not self._extract_first_doi(normalized):
            return False
        if self._detect_doi_requested_fields(normalized):
            return True
        field_hits = sum(1 for pattern in self.DOI_METADATA_FIELD_PATTERNS if pattern.search(normalized))
        has_request_phrase = bool(self.DOI_METADATA_REQUEST_PATTERN.search(normalized))
        has_info_phrase = bool(self.DOI_INFO_PATTERN.search(normalized))
        return has_info_phrase and (has_request_phrase or field_hits >= 3)

    def _detect_doi_requested_fields(self, text: str) -> list[str]:
        normalized = (text or "").strip()
        if not normalized or not self._extract_first_doi(normalized):
            return []
        matched_fields: list[str] = []
        for field_name, pattern in self.DOI_REQUESTED_FIELD_PATTERNS:
            if pattern.search(normalized):
                matched_fields.append(field_name)
        return matched_fields

    def _detect_doi_requested_field(self, text: str) -> str | None:
        matched_fields = self._detect_doi_requested_fields(text)
        if len(matched_fields) != 1:
            return None
        return matched_fields[0]

    @staticmethod
    def detect_requested_metadata_field(text: str) -> str | None:
        normalized = (text or "").strip()
        if not normalized:
            return None
        matched_fields: list[str] = []
        for field_name, pattern in ChatService.DOI_REQUESTED_FIELD_PATTERNS:
            if pattern.search(normalized):
                matched_fields.append(field_name)
        if len(matched_fields) != 1:
            return None
        return matched_fields[0]

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

    @classmethod
    def _normalize_author_details(cls, values: list[Any] | None) -> list[dict[str, str | None]]:
        normalized: list[dict[str, str | None]] = []
        seen: set[str] = set()

        for value in values or []:
            given: str | None = None
            family: str | None = None
            name: str | None = None

            if isinstance(value, dict):
                given = cls._clean_metadata_text(value.get("given"))
                family = cls._clean_metadata_text(value.get("family"))
                name = (
                    cls._clean_metadata_text(value.get("name"))
                    or cls._clean_metadata_text(value.get("full_name"))
                )
                if not name:
                    name = " ".join(part for part in [given, family] if part).strip() or None
            else:
                name = cls._clean_metadata_text(str(value))

            if not name:
                continue
            key = normalize_author_name(name) or name.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append({
                "given": given,
                "family": family,
                "name": name,
            })

        return normalized

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
        cleaned_author_details = cls._normalize_author_details(authors)
        cleaned_authors = [str(item.get("name")) for item in cleaned_author_details if item.get("name")]
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
            "author_details": cleaned_author_details,
            "author_count": len(cleaned_authors),
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
            sorted_authors = sorted(
                article.authors,
                key=lambda author: (
                    getattr(author, "author_order", None) is None,
                    getattr(author, "author_order", None) if getattr(author, "author_order", None) is not None else 9999,
                    str(getattr(author, "full_name", "") or ""),
                ),
            )
            authors = [author.full_name for author in sorted_authors if author.full_name]
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

        crossref_authors = [
            {
                "given": item.get("given"),
                "family": item.get("family"),
                "name": " ".join(
                    part.strip()
                    for part in [str(item.get("given") or "").strip(), str(item.get("family") or "").strip()]
                    if part and part.strip()
                ) or None,
            }
            for item in crossref.get("author", [])
            if isinstance(item, dict) and (item.get("given") or item.get("family"))
        ]
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
            authors=crossref_authors or result.authors or openalex_authors,
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

    @staticmethod
    def _format_numbered_text_list(values: list[str]) -> str:
        return "\n".join(f"{index}. {value}" for index, value in enumerate(values, start=1))

    def _build_doi_requested_field_response(
        self,
        metadata: dict[str, Any],
        status: str,
        requested_field: str | None,
    ) -> str | None:
        if not requested_field:
            return None

        doi = str(metadata.get("doi") or "").strip()
        title = str(metadata.get("title") or "").strip()
        source = str(metadata.get("source") or "").strip()
        journal = str(metadata.get("journal") or metadata.get("venue") or "").strip()
        publisher = str(metadata.get("publisher") or "").strip()
        authors = self._dedupe_text_list(metadata.get("authors") or [])
        publication_year = metadata.get("publication_year") or metadata.get("year")
        research_field = str(metadata.get("research_field") or "").strip()
        main_topic = str(metadata.get("main_topic") or "").strip()
        abstract = str(metadata.get("abstract") or "").strip()

        field_labels = {
            "authors": "danh sách tác giả",
            "title": "tiêu đề bài báo",
            "journal": "tạp chí",
            "publisher": "nhà xuất bản",
            "publication_year": "năm xuất bản",
            "research_field": "lĩnh vực nghiên cứu",
            "main_topic": "chủ đề chính",
            "abstract": "tóm tắt",
        }

        if status != "verified":
            return (
                f"Mình chưa xác minh được DOI này nên chưa thể trả lời chính xác về {field_labels.get(requested_field, 'metadata')}."
                f" {EXACT_RECORD_NOT_FOUND_MESSAGE} Bạn có thể cung cấp thêm tiêu đề, tác giả hoặc abstract để mình kiểm tra lại."
            )

        source_lines = []
        if source:
            source_lines.append(f"Nguồn metadata: {source}")
        if doi:
            source_lines.append(f"DOI: {doi}")
        source_text = "\n".join(source_lines)
        source_block = f"\n\n{source_text}" if source_text else ""
        title_prefix = f' của bài "{title}"' if title else ""

        if requested_field == "authors":
            if authors:
                return (
                    f"Các tác giả{title_prefix} là:\n\n"
                    f"{self._format_numbered_text_list(authors)}"
                    f"{source_block}"
                )
            return (
                f"Mình đã xác minh DOI này nhưng metadata nguồn chưa cung cấp danh sách tác giả rõ ràng.{source_block}"
            )

        if requested_field == "title":
            if title:
                return f'Tiêu đề của DOI {doi or "này"} là "{title}".{source_block}'
            return f"Mình đã xác minh DOI này nhưng metadata nguồn chưa cung cấp tiêu đề rõ ràng.{source_block}"

        if requested_field == "journal":
            if journal:
                return f'Bài "{title or doi or "này"}" được xuất bản trên tạp chí {journal}.{source_block}'
            return f"Mình đã xác minh DOI này nhưng metadata nguồn chưa ghi rõ tạp chí.{source_block}"

        if requested_field == "publisher":
            if publisher:
                return f'Nhà xuất bản của bài "{title or doi or "này"}" là {publisher}.{source_block}'
            return f"Mình đã xác minh DOI này nhưng metadata nguồn chưa ghi rõ nhà xuất bản.{source_block}"

        if requested_field == "publication_year":
            if publication_year:
                return f'Năm xuất bản của bài "{title or doi or "này"}" là {publication_year}.{source_block}'
            return f"Mình đã xác minh DOI này nhưng metadata nguồn chưa ghi rõ năm xuất bản.{source_block}"

        if requested_field == "research_field":
            if research_field:
                return f'Lĩnh vực nghiên cứu chính của bài "{title or doi or "này"}" là {research_field}.{source_block}'
            note = str(metadata.get("research_field_note") or "").strip()
            return f"{note or 'Mình đã xác minh DOI này nhưng metadata nguồn chưa ghi rõ lĩnh vực nghiên cứu.'}{source_block}"

        if requested_field == "main_topic":
            if main_topic:
                return f'Chủ đề chính của bài "{title or doi or "này"}" là {main_topic}.{source_block}'
            note = str(metadata.get("main_topic_note") or "").strip()
            return f"{note or 'Mình đã xác minh DOI này nhưng metadata nguồn chưa ghi rõ chủ đề chính.'}{source_block}"

        if requested_field == "abstract":
            if abstract:
                return f'Tóm tắt hiện có cho bài "{title or doi or "này"}":\n\n{abstract}{source_block}'
            return f"Mình đã xác minh DOI này nhưng metadata nguồn chưa có abstract.{source_block}"

        return None

    def _run_doi_metadata_lookup(
        self,
        db: Session,
        doi: str,
        user_message: str | None = None,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        metadata, status = self._resolve_doi_metadata(db, doi)
        requested_field = self._detect_doi_requested_field(user_message or "")
        text = self._build_doi_requested_field_response(metadata, status, requested_field)
        if not text:
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
            "requested_field": requested_field,
            "data": metadata,
        }
        return MessageType.TEXT, text, payload

    def _build_author_publication_summary(
        self,
        source_record: dict[str, Any] | None,
        result: AuthorPublicationLookupResult,
    ) -> str:
        if source_record is None:
            return (
                "Mình chưa resolve được DOI này thành một bài báo nguồn đáng tin cậy, "
                "nên chưa thể tra publication khác của tác giả."
            )

        title = str(source_record.get("title") or "bài báo này").strip()
        venue = str(source_record.get("venue") or "").strip()
        year = source_record.get("year")
        author_count = len(result.authors)
        authors_with_publications = sum(1 for author in result.authors if author.get("publications"))
        paper_bits = [f"DOI này là bài \"{title}\""]
        if venue:
            paper_bits.append(f"đăng trên {venue}")
        if year:
            paper_bits.append(f"năm {year}")
        paper_text = ", ".join(paper_bits) + "."

        if result.status == "matched":
            source_note = (
                " Mình đã kiểm tra thêm publication khác cho "
                f"{author_count} tác giả đã chọn và tìm thấy kết quả cho {authors_with_publications} tác giả."
            )
            if result.external_search_used:
                source_note += " Dữ liệu ngoài đã được dùng để mở rộng coverage khi tra tác giả."
            return paper_text + source_note + " Xem paper gốc, tác giả, publication và nguồn ở thẻ kết quả bên dưới."

        if result.status == "source_degraded":
            return (
                paper_text
                + " Mình đã bắt đầu tra publication theo tác giả, nhưng một hoặc nhiều nguồn học thuật bên ngoài bị lỗi hoặc timeout nên kết quả hiện chưa đầy đủ."
            )

        return (
            paper_text
            + " Mình đã lấy được danh sách tác giả, nhưng chưa tìm thấy publication khác đủ tin cậy ngoài bài gốc trong các nguồn đã kiểm tra."
        )

    def _build_named_author_publication_summary(
        self,
        author_name: str,
        result: AuthorPublicationLookupResult,
        *,
        source_record: dict[str, Any] | None,
        matched_from_context: bool,
        other_publications_only: bool,
    ) -> str:
        source_text = self._checked_source_names(result.checked_sources)
        context_note = ""
        if matched_from_context and source_record and source_record.get("title"):
            context_note = (
                f"Mình đã dùng context từ bài \"{source_record.get('title')}\" để match tác giả {author_name}. "
            )

        if result.status == "matched":
            action_text = "publication khác" if other_publications_only else "publication"
            fallback_note = (
                " Không đủ trong dữ liệu nội bộ nên mình đã tra thêm nguồn học thuật bên ngoài/websearch."
                if result.external_search_used
                else ""
            )
            return (
                f"{context_note}Mình đã tra {action_text} của {author_name}.{fallback_note} "
                "Xem danh sách publication và nguồn đã kiểm tra ở thẻ kết quả bên dưới."
            )

        if result.status == "source_degraded":
            return (
                f"{context_note}Mình đã kiểm tra dữ liệu nội bộ và các nguồn bên ngoài"
                f"{f' ({source_text})' if source_text else ''} cho {author_name}, "
                "nhưng một hoặc nhiều nguồn ngoài bị lỗi hoặc timeout nên kết quả hiện chưa đầy đủ."
            )

        return (
            f"{context_note}Mình đã kiểm tra dữ liệu nội bộ và các nguồn bên ngoài"
            f"{f' ({source_text})' if source_text else ''} cho {author_name}, "
            "nhưng chưa tìm thấy publication đủ tin cậy."
        )

    def _run_named_author_publication_search(
        self,
        db: Session,
        session_id: str,
        user_message: str,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        requested_author = self._extract_author_name_from_query(user_message)
        author_context, source_record, matched_from_context = self._resolve_author_context_from_history(
            db,
            session_id,
            requested_author,
        )

        author_payload = author_context
        if author_payload is None and requested_author:
            author_payload = {
                "name": requested_author,
                "confidence": 0.9,
                "notes": [],
            }

        if author_payload is None:
            payload = {
                "type": "author_publication_search",
                "status": "author_not_resolved",
                "query": user_message,
                "author": None,
                "source_doi": source_record.get("doi") if isinstance(source_record, dict) else None,
                "source_title": source_record.get("title") if isinstance(source_record, dict) else None,
                "source_record": source_record,
                "authors": [],
                "external_search_used": False,
                "fallback_used": False,
                "fallback_reason": "Author name could not be resolved from the query or recent session context.",
                "checked_sources": [],
                "notes": ["Author name could not be resolved from the query or recent session context."],
            }
            return (
                MessageType.TEXT,
                "Mình chưa xác định được chính xác tác giả bạn muốn tra publication. Bạn có thể gửi lại tên tác giả đầy đủ.",
                payload,
            )

        effective_author_name = str(author_payload.get("name") or requested_author or "").strip()
        other_publications_only = self._requests_other_publications(user_message)
        source_doi = str(source_record.get("doi") or "").strip() if isinstance(source_record, dict) else ""
        source_title = str(source_record.get("title") or "").strip() if isinstance(source_record, dict) else ""
        lookup_result = external_academic_search_service.lookup_author_publications(
            db,
            source_record=source_record,
            authors=[author_payload],
            source_doi=(source_doi or None) if other_publications_only else None,
            source_title=(source_title or None) if other_publications_only else None,
            max_authors=1,
        )
        checked_sources = lookup_result.checked_sources
        internal_state = next(
            (
                str(source.get("state") or "").strip().lower()
                for source in checked_sources
                if isinstance(source, dict) and str(source.get("name") or "").strip().casefold() == "internal academic database"
            ),
            "",
        )
        fallback_used = lookup_result.external_search_used and internal_state in {"no_match", "low_confidence", "skipped"}
        fallback_reason = "Internal DB returned 0 candidates" if internal_state == "no_match" else (
            "Internal DB confidence was too low" if internal_state == "low_confidence" else None
        )
        notes = list(lookup_result.notes)
        if matched_from_context:
            notes.insert(0, "Author identity was matched from the recent DOI/paper context in this session.")
        payload = {
            "type": "author_publication_search",
            "status": lookup_result.status,
            "query": user_message,
            "author": {
                "name": effective_author_name,
                "matched_from_context": matched_from_context,
                "source_paper_doi": source_doi or None,
                "source_paper_title": source_title or None,
            },
            "source_doi": source_doi or None,
            "source_title": source_title or None,
            "source_record": source_record,
            "authors": lookup_result.authors,
            "external_search_used": lookup_result.external_search_used,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "checked_sources": checked_sources,
            "notes": self._dedupe_text_list(notes),
        }
        return (
            MessageType.TEXT,
            self._build_named_author_publication_summary(
                effective_author_name,
                lookup_result,
                source_record=source_record,
                matched_from_context=matched_from_context,
                other_publications_only=other_publications_only,
            ),
            payload,
        )

    def _run_author_publication_search(
        self,
        db: Session,
        doi: str,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        normalized = citation_checker.normalize_doi(doi)
        source_record, authors, source_checked_sources, source_notes = self._resolve_doi_author_context(db, normalized)
        if source_record is None:
            payload = {
                "type": "author_publication_search",
                "status": "source_not_found",
                "source_doi": normalized,
                "source_title": None,
                "source_record": None,
                "authors": [],
                "external_search_used": False,
                "checked_sources": source_checked_sources,
                "notes": source_notes,
            }
            return (
                MessageType.TEXT,
                "Mình chưa resolve được DOI này thành một bài báo nguồn đủ tin cậy nên chưa thể tra publication theo tác giả.",
                payload,
            )

        lookup_result = external_academic_search_service.lookup_author_publications(
            db,
            source_record=source_record,
            authors=authors,
            source_doi=normalized,
            source_title=str(source_record.get("title") or ""),
        )
        checked_sources = external_academic_search_service._merge_checked_sources(
            source_checked_sources,
            lookup_result.checked_sources,
        )
        internal_state = next(
            (
                str(source.get("state") or "").strip().lower()
                for source in checked_sources
                if isinstance(source, dict) and str(source.get("name") or "").strip().casefold() == "internal academic database"
            ),
            "",
        )
        payload = {
            "type": "author_publication_search",
            "status": lookup_result.status,
            "source_doi": normalized,
            "source_title": source_record.get("title"),
            "source_record": source_record,
            "authors": lookup_result.authors,
            "external_search_used": lookup_result.external_search_used,
            "fallback_used": lookup_result.external_search_used and internal_state in {"no_match", "low_confidence", "skipped"},
            "fallback_reason": "Internal DB returned 0 candidates" if internal_state == "no_match" else (
                "Internal DB confidence was too low" if internal_state == "low_confidence" else None
            ),
            "checked_sources": checked_sources,
            "notes": self._dedupe_text_list([*source_notes, *lookup_result.notes]),
        }
        return MessageType.TEXT, self._build_author_publication_summary(source_record, lookup_result), payload

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

    @staticmethod
    def _extract_manuscript_fields_from_text(text: str) -> dict[str, str]:
        clean = ChatService._JOURNAL_INTENT_PREFIX_RE.sub("", text).strip()
        fields: dict[str, str] = {
            "title": "",
            "abstract": "",
            "keywords": "",
            "field": "",
        }
        label_map = {
            "title": "title", "tiêu đề": "title", "tieu de": "title",
            "abstract": "abstract", "tóm tắt": "abstract", "tom tat": "abstract",
            "keywords": "keywords", "từ khóa": "keywords", "tu khoa": "keywords",
            "subjects": "field",
            "field": "field", "subject": "field", "lĩnh vực": "field", "linh vuc": "field",
            "chủ đề": "field", "chu de": "field",
        }
        for match in ChatService._VN_EN_LABEL_RE.finditer(clean):
            raw_key = re.sub(r"\s+", " ", match.group("key").strip().lower())
            normalized_key = label_map.get(raw_key)
            if normalized_key and normalized_key in fields:
                value = match.group("value").strip().rstrip(".,;:")
                if value and not fields[normalized_key]:
                    fields[normalized_key] = value

        body = ChatService._VN_EN_LABEL_RE.sub("", clean).strip()
        body = ChatService._JOURNAL_INTENT_PREFIX_RE.sub("", body).strip()
        if body and not any(fields.values()):
            words = body.split()
            if len(words) >= 5:
                fields["abstract"] = body[:2000]
        if not fields["title"] and not fields["abstract"]:
            for sep in ("\n\n", "\n"):
                if sep in clean:
                    lines = [line.strip() for line in clean.split(sep) if line.strip()]
                    if lines and len(lines[0].split()) <= 30:
                        fields["title"] = lines[0]
                    if len(lines) > 1 and len(lines[1].split()) >= 10:
                        fields["abstract"] = lines[1][:2000]
                    break

        parts = []
        if fields["title"]:
            parts.append(f"Title: {fields['title']}")
        if fields["abstract"]:
            parts.append(f"{fields['abstract']}")
        if fields["keywords"]:
            parts.append(f"Keywords: {fields['keywords']}")
        if fields["field"]:
            parts.append(f"Subjects: {fields['field']}")
        fields["_canonical_text"] = "\n".join(parts) if parts else clean[:3000]
        return fields

    def _run_direct_journal_match(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        user_message: str,
        manuscript_fields: dict[str, str] | None = None,
    ) -> tuple[MessageType, str, dict[str, Any]]:
        if journal_match_service is None or build_chat_journal_match_payload is None:
            return MessageType.TEXT, (
                "Tính năng gợi ý tạp chí hiện chưa sẵn sàng trong môi trường này. "
                "Bạn vui lòng thử lại sau."
            ), {"type": "text", "error": "journal_match_service_unavailable"}

        if manuscript_fields is None:
            manuscript_fields = self._extract_manuscript_fields_from_text(user_message)
        canonical = manuscript_fields.get("_canonical_text", user_message)
        if len(canonical.strip()) < 30:
            return (
                MessageType.TEXT,
                "Mình cần thêm nội dung mô tả (abstract, keywords, lĩnh vực) để gợi ý tạp chí.",
                {"type": "journal_match", "matches": [], "status": "insufficient_manuscript_content"},
            )

        try:
            request = journal_match_service.create_match_request(
                db,
                current_user=current_user,
                payload=MatchRequestCreate(
                    text=canonical,
                    title=manuscript_fields.get("title"),
                    session_id=session_id,
                    top_k=5,
                    desired_venue_type="journal",
                    include_cfps=False,
                ),
            )
            journal_match_service.run_request(db, current_user=current_user, request_id=request.id)
            result = journal_match_service.get_result(db, current_user=current_user, request_id=request.id)
            _matches, summary, payload = build_chat_journal_match_payload(result)
            source_fields = {k: v for k, v in manuscript_fields.items() if not k.startswith("_") and v}
            payload["source_fields"] = source_fields
            return MessageType.TEXT, summary or "Đã hoàn tất gợi ý tạp chí.", payload
        except Exception as exc:
            logger.exception("Direct journal match failed for session %s", session_id)
            return MessageType.TEXT, (
                "Mình chưa xử lý được yêu cầu tìm kiếm tạp chí cho nội dung này. "
                "Bạn vui lòng kiểm tra lại nội dung hoặc thử lại sau."
            ), {"type": "text", "error": str(exc)}

    def _build_journal_match_items(
        self,
        result: dict[str, Any],
        journals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        matching_items: list[dict[str, Any]] = []
        for row in journals:
            metrics = {
                "impact_factor": row.get("impact_factor"),
                "h_index": row.get("h_index"),
                "review_time_weeks": row.get("review_time_weeks"),
                "acceptance_rate": row.get("acceptance_rate"),
                "open_access": row.get("open_access"),
                "citescore": row.get("citescore"),
                "sjr_quartile": row.get("sjr_quartile"),
                "jcr_quartile": row.get("jcr_quartile"),
                "indexed_scopus": row.get("indexed_scopus"),
                "indexed_wos": row.get("indexed_wos"),
            }
            matching_items.append({
                "journal": row.get("journal", ""),
                "venue_id": row.get("venue_id"),
                "venue_type": row.get("venue_type"),
                "score": row.get("score"),
                "reason": row.get("reason"),
                "subject_fit": row.get("scope_fit"),
                "publisher": row.get("publisher"),
                "url": row.get("url"),
                "supporting_evidence": row.get("supporting_evidence"),
                "warning_flags": row.get("warning_flags"),
                "metric_provenance": row.get("metric_provenance"),
                "unverified_metrics": row.get("unverified_metrics"),
                "metrics": metrics,
            })
        return matching_items

    def _run_general_qa_flow(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        user_message: str,
        pre_save_history: list[ChatMessage],
        user_ai_rule_phrases: list[str],
        user_ai_runtime_rules: list[dict[str, Any]],
    ) -> tuple[MessageType, str, dict[str, Any] | None]:
        file_context = self._get_file_context(db, session_id)
        user_message_with_context = self._build_file_context(db, session_id, user_message)

        doi = self._extract_first_doi(user_message_with_context)
        exact_identifiers = citation_checker.extract_exact_identifiers(user_message_with_context)

        if self.JOURNAL_INTENT_PATTERN.search(user_message or ""):
            manuscript_fields = self._extract_manuscript_fields_from_text(user_message)
            has_content = bool(manuscript_fields.get("title") or manuscript_fields.get("abstract") or manuscript_fields.get("keywords") or manuscript_fields.get("field"))
            if has_content and doi:
                return self._run_journal_match_from_doi(
                    db,
                    current_user=current_user,
                    session_id=session_id,
                    doi=doi,
                )
            if has_content:
                return self._run_direct_journal_match(
                    db,
                    current_user=current_user,
                    session_id=session_id,
                    user_message=user_message,
                    manuscript_fields=manuscript_fields,
                )
            if doi:
                return self._run_journal_match_from_doi(
                    db,
                    current_user=current_user,
                    session_id=session_id,
                    doi=doi,
                )
            latest_record = self._latest_resolved_record(db, session_id)
            if latest_record is not None and self._should_reuse_latest_record(user_message, latest_record, journal_intent=True):
                return self._run_journal_match_from_resolved_record(
                    db,
                    current_user=current_user,
                    session_id=session_id,
                    record=latest_record,
                )
            if not file_context and external_academic_search_service.should_handle(user_message):
                lookup_result = None
                try:
                    msg_type, content, payload = self._run_journal_match_from_lookup_text(
                        db,
                        current_user=current_user,
                        session_id=session_id,
                        user_message=user_message,
                        latest_record=latest_record,
                    )
                    lookup_result = payload
                except Exception:
                    logger.debug("External journal lookup degraded, falling back to direct match", exc_info=True)
                if lookup_result is None or (isinstance(lookup_result, dict) and lookup_result.get("status") in ("source_degraded", "record_not_found")):
                    manuscript_fields = self._extract_manuscript_fields_from_text(user_message)
                    has_content = bool(manuscript_fields.get("title") or manuscript_fields.get("abstract") or manuscript_fields.get("keywords") or manuscript_fields.get("field"))
                    if has_content:
                        return self._run_direct_journal_match(
                            db,
                            current_user=current_user,
                            session_id=session_id,
                            user_message=user_message,
                            manuscript_fields=manuscript_fields,
                        )
                if lookup_result:
                    return msg_type, content, payload

        if doi:
            if self._is_author_publication_request(user_message):
                return self._run_author_publication_search(db, doi)

            if self._is_doi_metadata_request(user_message):
                return self._run_doi_metadata_lookup(db, doi, user_message=user_message)

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

        if not file_context:
            latest_record = self._latest_resolved_record(db, session_id)
            if self._is_author_publication_request(user_message):
                named_author = self._extract_author_name_from_query(user_message)
                if named_author or self.AUTHOR_QUERY_PATTERN.search(user_message or ""):
                    named_result = self._run_named_author_publication_search(db, session_id, user_message)
                    named_payload = named_result[2]
                    if not (isinstance(named_payload, dict) and named_payload.get("status") == "author_not_resolved"):
                        return named_result
                if latest_record is not None:
                    latest_doi = str(latest_record.get("doi") or "").strip()
                    if latest_doi:
                        return self._run_author_publication_search(db, latest_doi)
            if latest_record is not None and self._should_reuse_latest_record(user_message, latest_record):
                return self._run_record_followup_qa(
                    user_message,
                    pre_save_history,
                    latest_record,
                    user_ai_rule_phrases,
                    user_ai_runtime_rules,
                )
            if external_academic_search_service.should_handle(user_message):
                return self._run_academic_lookup_flow(db, user_message)

        intent = self._classify_academic_intent(user_message)
        if intent == "general_academic_discussion":
            fc_response = gemini_service.generate_response(
                history=pre_save_history,
                user_text=user_message_with_context,
                system_prompt_override=AIRA_GENERAL_ACADEMIC_PROMPT,
                expose_tools=False,
                user_ai_rule_phrases=user_ai_rule_phrases,
                user_ai_runtime_rules=user_ai_runtime_rules,
            )
            return MessageType.TEXT, fc_response.text, None

        fc_response = gemini_service.generate_response(
            history=pre_save_history,
            user_text=user_message_with_context,
            user_ai_rule_phrases=user_ai_rule_phrases,
            user_ai_runtime_rules=user_ai_runtime_rules,
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
        user_ai_runtime_rules: list[dict[str, Any]],
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
            return self._finalize_auto_response(
                route,
                *self._run_doi_metadata_lookup(db, raw_user_doi, user_message=user_message),
            )

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
            manuscript_fields = self._extract_manuscript_fields_from_text(user_message)
            has_content = bool(manuscript_fields.get("title") or manuscript_fields.get("abstract") or manuscript_fields.get("keywords") or manuscript_fields.get("field"))
            if has_content:
                return self._finalize_auto_response(
                    route,
                    *self._run_direct_journal_match(
                        db,
                        current_user=current_user,
                        session_id=session_id,
                        user_message=user_message,
                        manuscript_fields=manuscript_fields,
                    ),
                )
            latest_record = self._latest_resolved_record(db, session_id) if not file_context else None
            if latest_record is not None and self._should_reuse_latest_record(user_message, latest_record, journal_intent=True):
                return self._finalize_auto_response(
                    route,
                    *self._run_journal_match_from_resolved_record(
                        db,
                        current_user=current_user,
                        session_id=session_id,
                        record=latest_record,
                    ),
                )
            if not file_context and external_academic_search_service.should_handle(user_message):
                return self._finalize_auto_response(
                    route,
                    *self._run_journal_match_from_lookup_text(
                        db,
                        current_user=current_user,
                        session_id=session_id,
                        user_message=user_message,
                        latest_record=latest_record,
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
            user_ai_runtime_rules,
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
        user_ai_runtime_rules = get_runtime_rule_payloads(
            db,
            current_user,
            use_custom_rules=True,
        )

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
                user_ai_runtime_rules,
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
            file_context = self._get_file_context(db, session_id)
            tool_input = self._build_file_context(db, session_id, user_message)
            if mode == SessionMode.VERIFICATION and self._is_doi_metadata_request(user_message):
                doi = self._extract_first_doi(tool_input)
                if doi:
                    msg_type, content, structured = self._run_doi_metadata_lookup(
                        db,
                        doi,
                        user_message=user_message,
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
            if mode == SessionMode.JOURNAL_MATCH:
                if file_context:
                    msg_type, content, structured = self._run_mode_tool(
                        db, current_user, session_id, mode, tool_input
                    )
                else:
                    manuscript_fields = self._extract_manuscript_fields_from_text(user_message)
                    canonical = manuscript_fields.get("_canonical_text", user_message)
                    if len(canonical.strip()) < 30:
                        msg_type = MessageType.TEXT
                        content = "Mình cần thêm nội dung mô tả (abstract, keywords, lĩnh vực) để gợi ý tạp chí."
                        structured = {"type": "journal_match", "matches": [], "status": "insufficient_manuscript_content"}
                    else:
                        msg_type, content, structured = self._run_mode_tool(
                            db, current_user, session_id, mode, canonical
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
            user_ai_runtime_rules,
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
