from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class VenueMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venue_metrics"

    venue_id: Mapped[str] = mapped_column(String(36), ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    metric_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    sjr_quartile: Mapped[str | None] = mapped_column(String(8), nullable=True)
    jcr_quartile: Mapped[str | None] = mapped_column(String(8), nullable=True)
    citescore: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    h_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acceptance_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_review_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    venue = relationship("Venue", back_populates="metrics")
