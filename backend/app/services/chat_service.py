from dataclasses import asdict
import re
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.authorization import AccessGateway
from app.core.config import settings
from app.models.chat_message import ChatMessage, MessageRole, MessageType
from app.models.chat_session import ChatSession, SessionMode
from app.models.file_attachment import FileAttachment
from app.models.user import User
from app.services.llm_service import gemini_service
from app.services.tools.ai_writing_detector import ai_writing_detector
from app.services.tools.citation_checker import citation_checker
from app.services.tools.journal_finder import journal_finder
from app.services.tools.retraction_scan import retraction_scanner


class ChatService:
    DEFAULT_SESSION_TITLE = "Trò chuyện mới"
    _LEGACY_DEFAULT_TITLES = {"new chat", "trò chuyện mới"}
    FILE_HINT_PATTERN = re.compile(r"\b(pdf|file|document|paper|manuscript|tom tat|summary|summarize)\b", re.IGNORECASE)
    _FILE_CONTEXT_MAX_CHARS = 15_000

    def create_session(self, db: Session, current_user: User, title: str, mode: SessionMode) -> ChatSession:
        clean_title = (title or "").strip() or self.DEFAULT_SESSION_TITLE
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

    def _is_default_title(self, title: str | None) -> bool:
        normalized = (title or "").strip().lower()
        return normalized in self._LEGACY_DEFAULT_TITLES

    def _run_mode_tool(self, mode: SessionMode, text: str) -> tuple[MessageType, str, dict[str, Any]]:
        if mode == SessionMode.VERIFICATION:
            citation_results = citation_checker.verify(text)
            data = [asdict(item) for item in citation_results]
            stats = citation_checker.get_statistics(citation_results)
            total = int(stats.get("total", 0) or 0)
            if bool(stats.get("no_citation_found", False)) or total == 0:
                summary = (
                    "Không phát hiện mẫu citation/DOI hợp lệ trong nội dung đã cung cấp, "
                    "nên chưa có mục nào để xác minh."
                )
            else:
                valid = int(stats.get("valid", 0) or 0) + int(stats.get("doi_verified", 0) or 0)
                partial = int(stats.get("partial_match", 0) or 0)
                hallucinated = int(stats.get("hallucinated", 0) or 0)
                unverified = int(stats.get("unverified", 0) or 0)
                summary = (
                    f"Đã xác minh {total} citation: {valid} hợp lệ, "
                    f"{partial} khớp một phần, {hallucinated} có dấu hiệu sai/hallucinated, "
                    f"{unverified} chưa xác minh được."
                )
            return MessageType.CITATION_REPORT, summary, {"type": "citation_report", "data": data}

        if mode == SessionMode.JOURNAL_MATCH:
            journals = journal_finder.recommend(text)
            summary = "I recommended journals based on abstract-topic similarity."
            return MessageType.JOURNAL_LIST, summary, {"type": "journal_list", "data": journals}

        if mode == SessionMode.RETRACTION:
            raw_results = retraction_scanner.scan(text)
            retraction = [asdict(item) for item in raw_results]
            stats = retraction_scanner.get_summary(raw_results)
            total_checked = int(stats.get("total_checked", stats.get("total", 0)) or 0)
            if bool(stats.get("no_doi_found", False)) or total_checked == 0:
                summary = (
                    "Không phát hiện DOI hợp lệ trong nội dung đã cung cấp, "
                    "nên chưa có mục nào để quét trạng thái retraction."
                )
            else:
                retracted = int(stats.get("retracted", 0) or 0)
                concerns = int(stats.get("concerns", 0) or 0)
                corrected = int(stats.get("corrected", 0) or 0)
                active = int(stats.get("active", 0) or 0)
                pubpeer = int(stats.get("pubpeer_discussions", 0) or 0)
                summary = (
                    f"Đã quét {total_checked} DOI: "
                    f"{retracted} RETRACTED, {concerns} CONCERN, "
                    f"{corrected} CORRECTED, {active} ACTIVE."
                )
                if pubpeer > 0:
                    summary += (
                        f" Có {pubpeer} DOI có thảo luận PubPeer "
                        "(không đồng nghĩa tự động với RETRACTED)."
                    )
            return MessageType.RETRACTION_REPORT, summary, {"type": "retraction_report", "data": retraction}

        if mode == SessionMode.AI_DETECTION:
            result = ai_writing_detector.analyze(text)
            data = asdict(result)
            summary = f"AI writing detection: score={data['score']}, verdict={data['verdict']}."
            return MessageType.AI_WRITING_DETECTION, summary, {"type": "ai_writing_detection", "data": data}

        # Fallback (should not reach here)
        retraction = [asdict(item) for item in retraction_scanner.scan(text)]
        summary = "Retraction scan completed on detected DOI(s)."
        return MessageType.RETRACTION_REPORT, summary, {"type": "retraction_report", "data": retraction}

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
            and self._is_default_title(session_obj.title)
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
            session_obj.title = gemini_service.generate_chat_title(user_message)
            db.add(session_obj)
            db.commit()
            db.refresh(session_obj)

        mode = session_obj.mode
        if mode in {
            SessionMode.VERIFICATION,
            SessionMode.JOURNAL_MATCH,
            SessionMode.RETRACTION,
            SessionMode.AI_DETECTION,
        }:
            # Inject file context so explicit tool modes also see the PDF text
            tool_input = self._build_file_context(db, session_id, user_message)
            msg_type, content, structured = self._run_mode_tool(mode, tool_input)
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
