from datetime import datetime

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import CrawlJobStatus, CrawlJobType, TimestampMixin, UUIDPrimaryKeyMixin, enum_values


class CrawlJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crawl_jobs"

    source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("crawl_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    requested_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    job_type: Mapped[CrawlJobType] = mapped_column(SqlEnum(CrawlJobType, values_callable=enum_values), nullable=False)
    status: Mapped[CrawlJobStatus] = mapped_column(
        SqlEnum(CrawlJobStatus, values_callable=enum_values),
        default=CrawlJobStatus.PENDING,
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_deduped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_indexed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    source = relationship("CrawlSource", back_populates="jobs")
    requested_by = relationship("User")
