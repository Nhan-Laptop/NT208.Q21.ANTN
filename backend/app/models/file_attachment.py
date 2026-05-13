import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.encrypted_types import EncryptedText
from app.core.sa_compat import Mapped, mapped_column


class FileAttachment(Base):
    __tablename__ = "file_attachments"
    __table_args__ = (
        Index("ix_fileatt_session_created", "session_id", "created_at"),
        Index("ix_fileatt_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), index=True, nullable=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    storage_url: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    storage_encrypted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    storage_encryption_alg: Mapped[str] = mapped_column(String(64), default="AES-256-GCM", nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    session = relationship("ChatSession", back_populates="attachments")
    message = relationship("ChatMessage", back_populates="attachments")
