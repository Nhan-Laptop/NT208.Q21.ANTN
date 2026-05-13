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
from app.services.llm_service import gemini_service
from app.services.journal_match.service import build_legacy_journal_payload, journal_match_service
from app.services.journal_match.topic_profile import ManuscriptTopicProfile
from app.services.tools.ai_writing_detector import ai_writing_detector
from app.services.tools.citation_checker import citation_checker
from app.services.tools.retraction_scan import retraction_scanner, scan_verified_retractions


logger = logging.getLogger(__name__)


class ChatService:
    DEFAULT_SESSION_TITLE = "Trò chuyện mới"
    _LEGACY_DEFAULT_TITLES = {"new chat", "trò chuyện mới"}
    _MODE_DEFAULT_TITLES: dict[SessionMode, str] = {
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
                )
                return MessageType.CITATION_REPORT, summary, {"type": "citation_report", "data": data}
            except Exception as exc:
                logger.exception("VERIFICATION mode failed for session %s", session_id)
                return MessageType.TEXT, (
                    "Mình chưa xác minh được trích dẫn cho nội dung này. "
                    "Bạn có thể thử lại hoặc gửi DOI/trích dẫn cụ thể hơn."
                ), {"type": "text", "error": str(exc)}

        if mode == SessionMode.JOURNAL_MATCH:
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
                result = ai_writing_detector.analyze(text)
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
            metadata = {
                "status": "verified",
                "source": USER_SAFE_CORPUS_LABEL,
                "doi": normalized,
                "title": article.title,
                "abstract": article.abstract,
                "year": article.publication_year,
                "venue": article.venue.title if article.venue else None,
                "authors": authors,
                "subjects": subjects,
                "keywords": keywords,
                "url": article.url,
            }
            return metadata, "verified"

        result = citation_checker.verify_doi_exact(normalized)
        if result.status != "DOI_VERIFIED":
            metadata = {
                "status": "not_found",
                "source": result.source,
                "doi": normalized,
            }
            return metadata, "not_found"

        meta = result.metadata or {}
        crossref = meta.get("crossref") or {}
        openalex = meta.get("openalex") or {}

        def _strip_html(value: str | None) -> str | None:
            if not value:
                return value
            return re.sub(r"<[^>]+>", " ", value).strip()

        subjects: list[str] = []
        if crossref.get("subject"):
            subjects = [str(item).strip() for item in crossref.get("subject", []) if str(item).strip()]
        elif openalex.get("concepts"):
            subjects = [
                str(item.get("display_name")).strip()
                for item in openalex.get("concepts", [])
                if item.get("display_name")
            ]

        venue = None
        if crossref.get("container-title"):
            venue = str(crossref.get("container-title", [""])[0]).strip() or None
        elif openalex.get("host_venue"):
            venue = openalex.get("host_venue", {}).get("display_name")

        metadata = {
            "status": "verified",
            "source": result.source,
            "doi": normalized,
            "title": result.title,
            "abstract": _strip_html(crossref.get("abstract")) or _strip_html(openalex.get("abstract")),
            "year": result.year,
            "venue": venue,
            "authors": result.authors or [],
            "subjects": subjects,
            "keywords": [],
            "url": crossref.get("URL") or openalex.get("id"),
        }
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
                f"{EXACT_RECORD_NOT_FOUND_MESSAGE} "
                f"Bạn có thể cung cấp thêm tiêu đề, tác giả, hoặc abstract để mình kiểm tra lại trong {USER_SAFE_DATA_LABEL}."
            )
        else:
            text = (
                f"Mình đã tìm thấy thông tin bài báo trong {USER_SAFE_DATA_LABEL}. "
                "Bạn có thể xem tóm tắt và metadata ở thẻ kết quả bên dưới."
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

    def complete_chat(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        user_message: str,
        mode_override: SessionMode | None = None,
    ) -> tuple[ChatMessage, ChatMessage, ChatSession]:
        session_obj = AccessGateway.assert_session_access(db, current_user, session_id)

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
        if mode in {
            SessionMode.VERIFICATION,
            SessionMode.JOURNAL_MATCH,
            SessionMode.RETRACTION,
            SessionMode.AI_DETECTION,
        }:
            # Inject file context so explicit tool modes also see the PDF text
            tool_input = self._build_file_context(db, session_id, user_message)
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

        # General Q&A mode — use pre_save_history (no current-msg duplication)
        user_message_with_context = self._build_file_context(db, session_id, user_message)

        doi = self._extract_first_doi(user_message_with_context)
        if doi:
            if self.JOURNAL_INTENT_PATTERN.search(user_message or ""):
                msg_type, content, structured = self._run_journal_match_from_doi(
                    db,
                    current_user=current_user,
                    session_id=session_id,
                    doi=doi,
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

            if self.CITATION_VERIFY_PATTERN.search(user_message or ""):
                msg_type, content, structured = self._run_mode_tool(
                    db,
                    current_user,
                    session_id,
                    SessionMode.VERIFICATION,
                    user_message_with_context,
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

            if self.DOI_INFO_PATTERN.search(user_message or ""):
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

        academic_query_result = None
        if not self._get_file_context(db, session_id) and academic_query_service.should_handle(user_message):
            academic_query_result = academic_query_service.answer(db, user_message)
        if academic_query_result is not None:
            assistant_msg = self._save_message(
                db=db,
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=academic_query_result.text,
                message_type=MessageType.TEXT,
                tool_results={
                    "type": "academic_lookup",
                    "status": "no_data" if not academic_query_result.records else "found",
                    "data": {
                        "records": academic_query_result.records,
                        "count": len(academic_query_result.records),
                    },
                },
            )
            db.refresh(session_obj)
            return user_msg, assistant_msg, session_obj

        # ── General academic discussion routing ──
        if not academic_query_result:
            intent = self._classify_academic_intent(user_message)
            if intent == "general_academic_discussion":
                fc_response = gemini_service.generate_response(
                    history=pre_save_history,
                    user_text=user_message_with_context,
                    system_prompt_override=AIRA_GENERAL_ACADEMIC_PROMPT,
                    expose_tools=False,
                )
                assistant_msg = self._save_message(
                    db=db,
                    session_id=session_id,
                    role=MessageRole.ASSISTANT,
                    content=fc_response.text,
                    message_type=MessageType.TEXT,
                    tool_results=None,
                )
                db.refresh(session_obj)
                return user_msg, assistant_msg, session_obj

        fc_response = gemini_service.generate_response(
            history=pre_save_history, user_text=user_message_with_context,
        )

        # Determine MessageType from function calling result
        try:
            msg_type = MessageType(fc_response.message_type)
        except (ValueError, KeyError):
            msg_type = MessageType.TEXT

        assistant_msg = self._save_message(
            db=db,
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=fc_response.text,
            message_type=msg_type,
            tool_results=fc_response.tool_results,
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
