from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class CrawlSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crawl_sources"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_crawled_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    states = relationship("CrawlState", back_populates="source", cascade="all, delete-orphan")
    jobs = relationship("CrawlJob", back_populates="source")
    raw_snapshots = relationship("RawSourceSnapshot", back_populates="source", cascade="all, delete-orphan")
