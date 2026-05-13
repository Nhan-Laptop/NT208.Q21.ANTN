from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class RawSourceSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "raw_source_snapshots"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", "content_hash", name="uq_raw_snapshot_source_external_content"),
    )

    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("crawl_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    snapshot_type: Mapped[str] = mapped_column(String(64), nullable=False)
    request_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    crawl_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    normalized_url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source = relationship("CrawlSource", back_populates="raw_snapshots")
