from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class CFPEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cfp_events"

    venue_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("venues.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    abstract_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    full_paper_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    indexed_scopus: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    indexed_wos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    venue = relationship("Venue", back_populates="cfp_events")
