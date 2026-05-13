from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class Manuscript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "manuscripts"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    file_attachment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("file_attachments.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    keywords_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    references_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    parsed_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user = relationship("User")
    session = relationship("ChatSession")
    file_attachment = relationship("FileAttachment")
    assessments = relationship("ManuscriptAssessment", back_populates="manuscript", cascade="all, delete-orphan")
    match_requests = relationship("MatchRequest", back_populates="manuscript", cascade="all, delete-orphan")
