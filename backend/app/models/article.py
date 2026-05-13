from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class Article(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "articles"

    venue_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("venues.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    indexed_scopus: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    indexed_wos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_retracted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    venue = relationship("Venue", back_populates="articles")
    authors = relationship("ArticleAuthor", back_populates="article", cascade="all, delete-orphan")
    keywords = relationship("ArticleKeyword", back_populates="article", cascade="all, delete-orphan")
