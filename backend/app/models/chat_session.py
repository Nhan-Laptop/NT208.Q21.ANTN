import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SessionMode(str, Enum):
    GENERAL_QA = "general_qa"
    VERIFICATION = "verification"
    JOURNAL_MATCH = "journal_match"
    RETRACTION = "retraction"
    AI_DETECTION = "ai_detection"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="Trò chuyện mới")
    mode: Mapped[SessionMode] = mapped_column(SqlEnum(SessionMode), default=SessionMode.GENERAL_QA, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )

    user = relationship("User", back_populates="sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    attachments = relationship("FileAttachment", back_populates="session", cascade="all, delete-orphan")
