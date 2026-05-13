from sqlalchemy import Boolean, Enum as SqlEnum, Float, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin, VenueType, enum_values


class Venue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venues"

    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    canonical_title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    venue_type: Mapped[VenueType] = mapped_column(
        SqlEnum(VenueType, values_callable=enum_values),
        nullable=False,
        index=True,
    )
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    issn_print: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    issn_electronic: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    homepage_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    aims_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    indexed_scopus: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    indexed_wos: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_open_access: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_hybrid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    avg_review_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acceptance_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    apc_usd_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    apc_usd_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    aliases = relationship("VenueAlias", back_populates="venue", cascade="all, delete-orphan")
    metrics = relationship("VenueMetric", back_populates="venue", cascade="all, delete-orphan")
    subjects = relationship("VenueSubject", back_populates="venue", cascade="all, delete-orphan")
    policies = relationship("VenuePolicy", back_populates="venue", cascade="all, delete-orphan")
    articles = relationship("Article", back_populates="venue")
    cfp_events = relationship("CFPEvent", back_populates="venue")
