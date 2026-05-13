import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from app.core.sa_compat import Mapped, mapped_column


def enum_values(enum_cls: type[Enum]) -> list[str]:
    return [item.value for item in enum_cls]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPrimaryKeyMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class CrawlJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CrawlJobType(str, Enum):
    CRAWL = "crawl"
    REINDEX = "reindex"


class VenueType(str, Enum):
    JOURNAL = "journal"
    CONFERENCE = "conference"
    WORKSHOP = "workshop"
    CFP = "cfp"


class MatchRequestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EntityType(str, Enum):
    VENUE = "venue"
    ARTICLE = "article"
    CFP = "cfp"


ScalarBool = mapped_column(Boolean, default=False, nullable=False)
ScalarFloat = mapped_column(Float, nullable=True)
ScalarInt = mapped_column(Integer, nullable=True)
ScalarJSON = mapped_column(JSON, nullable=True)
ScalarString255 = mapped_column(String(255), nullable=True)
ScalarText = mapped_column(Text, nullable=True)
