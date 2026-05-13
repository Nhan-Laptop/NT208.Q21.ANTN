import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.encrypted_types import EncryptedJSON, EncryptedText
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import enum_values


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageType(str, Enum):
    TEXT = "text"
    CITATION_REPORT = "citation_report"
    JOURNAL_LIST = "journal_list"
    RETRACTION_REPORT = "retraction_report"
    FILE_UPLOAD = "file_upload"
    PDF_SUMMARY = "pdf_summary"
    AI_WRITING_DETECTION = "ai_writing_detection"
    GRAMMAR_REPORT = "grammar_report"


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chatmsg_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[MessageRole] = mapped_column(SqlEnum(MessageRole, values_callable=enum_values), nullable=False)
    message_type: Mapped[MessageType] = mapped_column(
        SqlEnum(MessageType, values_callable=enum_values),
        default=MessageType.TEXT,
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    tool_results: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(EncryptedJSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    session = relationship("ChatSession", back_populates="messages")
    attachments = relationship("FileAttachment", back_populates="message", cascade="all, delete-orphan")
