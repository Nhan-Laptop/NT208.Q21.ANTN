from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Float, ForeignKey, JSON, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import MatchRequestStatus, TimestampMixin, UUIDPrimaryKeyMixin, enum_values


class MatchRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "match_requests"

    manuscript_id: Mapped[str] = mapped_column(String(36), ForeignKey("manuscripts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    desired_venue_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    min_quartile: Mapped[str | None] = mapped_column(String(8), nullable=True)
    require_scopus: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_wos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    apc_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_review_weeks: Mapped[float | None] = mapped_column(Float, nullable=True)
    include_cfps: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[MatchRequestStatus] = mapped_column(
        SqlEnum(MatchRequestStatus, values_callable=enum_values),
        default=MatchRequestStatus.PENDING,
        nullable=False,
        index=True,
    )
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retrieval_diagnostics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    manuscript = relationship("Manuscript", back_populates="match_requests")
    user = relationship("User")
    candidates = relationship("MatchCandidate", back_populates="match_request", cascade="all, delete-orphan")
