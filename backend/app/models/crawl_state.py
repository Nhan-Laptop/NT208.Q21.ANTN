from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class CrawlState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crawl_states"
    __table_args__ = (UniqueConstraint("source_id", name="uq_crawl_state_source_id"),)

    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("crawl_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    checkpoint_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    source = relationship("CrawlSource", back_populates="states")
