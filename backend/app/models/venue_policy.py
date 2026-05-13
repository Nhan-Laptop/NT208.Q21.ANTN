from sqlalchemy import Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class VenuePolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venue_policies"
    __table_args__ = (UniqueConstraint("venue_id", name="uq_venue_policy_venue"),)

    venue_id: Mapped[str] = mapped_column(String(36), ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    peer_review_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    open_access_policy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    copyright_policy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    archiving_policy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    apc_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnaround_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    venue = relationship("Venue", back_populates="policies")
