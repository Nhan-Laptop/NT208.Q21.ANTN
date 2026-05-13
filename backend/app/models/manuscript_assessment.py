from sqlalchemy import Boolean, ForeignKey, Integer, JSON, Float, UniqueConstraint, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class ManuscriptAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "manuscript_assessments"
    __table_args__ = (UniqueConstraint("manuscript_id", name="uq_manuscript_assessment_manuscript"),)

    manuscript_id: Mapped[str] = mapped_column(String(36), ForeignKey("manuscripts.id", ondelete="CASCADE"), nullable=False, index=True)
    readiness_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    title_present: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    abstract_present: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    keyword_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reference_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    manuscript = relationship("Manuscript", back_populates="assessments")
