from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class VenueAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venue_aliases"
    __table_args__ = (UniqueConstraint("venue_id", "alias_normalized", name="uq_venue_alias_normalized"),)

    venue_id: Mapped[str] = mapped_column(String(36), ForeignKey("venues.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(500), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    alias_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    venue = relationship("Venue", back_populates="aliases")
