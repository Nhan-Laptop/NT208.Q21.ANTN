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
from app.services.tools.citation_checker import citation_checker
from app.services.tools.journal_finder import journal_finder
from app.services.tools.retraction_scan import retraction_scanner


class ChatService:
    FILE_HINT_PATTERN = re.compile(r"\b(pdf|file|document|paper|manuscript|tom tat|summary|summarize)\b", re.IGNORECASE)

    def create_session(self, db: Session, current_user: User, title: str, mode: SessionMode) -> ChatSession:
        session_obj = ChatSession(user_id=current_user.id, title=title, mode=mode)
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

    def _derive_title(self, text: str) -> str:
        words = text.strip().split()
        if not words:
            return "New Chat"
        return " ".join(words[:8])[:255]

    def _run_mode_tool(self, mode: SessionMode, text: str) -> tuple[MessageType, str, dict[str, Any]]:
        if mode == SessionMode.VERIFICATION:
            citation_results = citation_checker.verify(text)
            data = [asdict(item) for item in citation_results]
            hallucinated = [x for x in data if x["status"] == "HALLUCINATED"]
            summary = f"Citation check finished. Found {len(hallucinated)} potential hallucinated citation(s)."
            return MessageType.CITATION_REPORT, summary, {"type": "citation_report", "data": data}

        if mode == SessionMode.JOURNAL_MATCH:
            journals = journal_finder.recommend(text)
            summary = "I recommended journals based on abstract-topic similarity."
            return MessageType.JOURNAL_LIST, summary, {"type": "journal_list", "data": journals}

        retraction = [asdict(item) for item in retraction_scanner.scan(text)]
        summary = "Retraction scan completed on detected DOI(s)."
        return MessageType.RETRACTION_REPORT, summary, {"type": "retraction_report", "data": retraction}

    def _build_file_context(self, db: Session, session_id: str, user_message: str) -> str:
        if not self.FILE_HINT_PATTERN.search(user_message):
            return user_message
        latest_file = (
            db.query(FileAttachment)
            .filter(FileAttachment.session_id == session_id)
            .order_by(desc(FileAttachment.created_at))
            .first()
        )
        if not latest_file or not latest_file.extracted_text:
            return user_message
        snippet = latest_file.extracted_text[:4000]
        return (
            f"{user_message}\n\n"
            f"[Attached file context: {latest_file.file_name}]\n"
            f"{snippet}"
        )

    def complete_chat(
        self,
        db: Session,
        current_user: User,
        session_id: str,
        user_message: str,
        mode_override: SessionMode | None = None,
    ) -> tuple[ChatMessage, ChatMessage]:
        session_obj = AccessGateway.assert_session_access(db, current_user, session_id)

        if mode_override and mode_override != session_obj.mode:
            session_obj.mode = mode_override

        if session_obj.title == "New Chat":
            session_obj.title = self._derive_title(user_message)

        db.add(session_obj)
        db.commit()

        user_msg = self._save_message(
            db=db,
            session_id=session_id,
            role=MessageRole.USER,
            content=user_message,
            message_type=MessageType.TEXT,
        )

        mode = session_obj.mode
        if mode in {SessionMode.VERIFICATION, SessionMode.JOURNAL_MATCH}:
            msg_type, content, structured = self._run_mode_tool(mode, user_message)
            assistant_msg = self._save_message(
                db=db,
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=content,
                message_type=msg_type,
                tool_results=structured,
            )
            return user_msg, assistant_msg

        # General Q&A mode with contextual memory
        history = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(settings.chat_context_window)
            .all()
        )
        history = list(reversed(history))
        user_message_with_context = self._build_file_context(db, session_id, user_message)
        assistant_text = gemini_service.generate_response(history=history, user_text=user_message_with_context)

        assistant_msg = self._save_message(
            db=db,
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=assistant_text,
            message_type=MessageType.TEXT,
        )
        return user_msg, assistant_msg

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
                "storage_url": attachment.storage_url,
                "storage_encrypted": attachment.storage_encrypted,
                "storage_encryption_alg": attachment.storage_encryption_alg,
            },
        }
        content = (
            f"Uploaded file `{attachment.file_name}`. "
            f"URL: {attachment.storage_url}. "
            f"Storage encryption: {attachment.storage_encryption_alg}."
        )
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
