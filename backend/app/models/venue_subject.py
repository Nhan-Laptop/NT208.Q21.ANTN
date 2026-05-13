from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class VenueSubject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venue_subjects"
    __table_args__ = (UniqueConstraint("venue_id", "label", name="uq_venue_subject"),)

    venue_id: Mapped[str] = mapped_column(String(36), ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    scheme: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    venue = relationship("Venue", back_populates="subjects")
