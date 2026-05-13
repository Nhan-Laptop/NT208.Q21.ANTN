from sqlalchemy import Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import EntityType, TimestampMixin, UUIDPrimaryKeyMixin


class MatchCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "match_candidates"

    match_request_id: Mapped[str] = mapped_column(String(36), ForeignKey("match_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, default=EntityType.VENUE.value)
    venue_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("venues.id", ondelete="SET NULL"), nullable=True, index=True)
    cfp_event_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cfp_events.id", ondelete="SET NULL"), nullable=True, index=True)
    article_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieval_score: Mapped[float] = mapped_column(Float, nullable=False)
    scope_overlap_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    quality_fit_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    policy_fit_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    manuscript_readiness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    penalty_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    explanation_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    match_request = relationship("MatchRequest", back_populates="candidates")
    venue = relationship("Venue")
    cfp_event = relationship("CFPEvent")
    article = relationship("Article")
