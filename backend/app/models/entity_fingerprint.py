from sqlalchemy import String, UniqueConstraint

from app.core.database import Base
from app.core.sa_compat import Mapped, mapped_column
from app.models.academic_common import TimestampMixin, UUIDPrimaryKeyMixin


class EntityFingerprint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_fingerprints"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "source_name", name="uq_entity_fingerprint_entity_source"),
    )

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    normalized_url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    business_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    raw_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
